"""
SEC EDGAR Insider Trading Tracker

Fetches Form 4 filings from SEC EDGAR for more detailed insider trade data
than yfinance provides: exact amounts, transaction codes, post-trade holdings.
"""

import logging
import requests
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": "invest-brief/0.1 (invest-brief@example.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml",
}

_TIMEOUT = 15

TX_CODES = {
    "A": "授予",
    "D": "出售",
    "F": "纳税出售",
    "G": "赠与",
    "M": "期权行权",
    "P": "公开市场买入",
    "S": "公开市场卖出",
    "V": "自愿申报",
}


def _get_filing_urls_from_atom(symbol: str) -> List[str]:
    """Parse Atom feed and return filing directory URLs."""
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={symbol}&type=4&dateb=&owner=only&count=5&output=atom"
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    ns = 'http://www.w3.org/2005/Atom'
    dirs = []

    for entry in root.findall(f'{{{ns}}}entry'):
        content = entry.find(f'{{{ns}}}content')
        if content is None:
            continue
        filing_href = content.find(f'{{{ns}}}filing-href')
        if filing_href is not None and filing_href.text:
            href = filing_href.text
            # URL format: /data/CIK/ACCESSION_NODASH/ACCESSION-index.htm
            # We need: /data/CIK/ACCESSION_NODASH
            if '-index.htm' in href:
                idx = href.rfind('-index.htm')
                base_dir = href[:idx].rsplit('/', 1)[0]
                dirs.append(base_dir)

    return dirs


def _parse_form4_xml(url: str) -> List[Dict[str, Any]]:
    """Parse a Form 4 XML filing and extract transactions."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()

        root = ET.fromstring(resp.content)
        transactions = []

        for elem in root.iter():
            tag = elem.tag.split('}')[-1] if '}' in elem.tag else elem.tag

            if tag == 'nonDerivativeTransaction':
                tx = {}
                for child in elem:
                    ctag = child.tag.split('}')[-1] if '}' in child.tag else child.tag
                    if ctag == 'transactionDate':
                        for d in child:
                            dtag = d.tag.split('}')[-1] if '}' in d.tag else d.tag
                            if dtag == 'value':
                                tx['date'] = d.text
                    elif ctag == 'transactionCoding':
                        for c in child:
                            cctag = c.tag.split('}')[-1] if '}' in c.tag else c.tag
                            if cctag == 'transactionCode':
                                tx['code'] = c.text
                    elif ctag == 'transactionAmounts':
                        for a in child:
                            atag = a.tag.split('}')[-1] if '}' in a.tag else a.tag
                            if atag == 'transactionShares':
                                for s in a:
                                    stag = s.tag.split('}')[-1] if '}' in s.tag else s.tag
                                    if stag == 'value':
                                        tx['shares'] = s.text
                            elif atag == 'transactionPricePerShare':
                                for p in a:
                                    ptag = p.tag.split('}')[-1] if '}' in p.tag else p.tag
                                    if ptag == 'value':
                                        tx['price'] = p.text
                            elif atag == 'transactionAcquiredDisposedCode':
                                for c in a:
                                    ctag2 = c.tag.split('}')[-1] if '}' in c.tag else c.tag
                                    if ctag2 == 'value':
                                        tx['action'] = '买入' if c.text == 'A' else '卖出' if c.text == 'D' else c.text

                if tx.get('date') and tx.get('code'):
                    transactions.append(tx)

        return transactions
    except Exception as e:
        logger.warning(f"Form 4 XML parse error: {e}")
        return []


def _find_xml_in_filing(base_dir: str) -> Optional[str]:
    """Fetch the filing index page and find the actual XML document URL."""
    try:
        # The index page URL has the accession with dashes
        parts = base_dir.rsplit('/', 1)
        accession_with_dashes = parts[1].replace('', '')  # already has dashes
        index_url = f"{base_dir}/{parts[-1]}-index.htm"
        resp = requests.get(index_url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        # Find XML file links in the index page
        import re
        xml_matches = re.findall(r'href="(/Archives/edgar/data/[^"]+\.xml)"', resp.text)
        # Prefer form4.xml or primary_doc.xml, skip xsl rendered versions
        for match in xml_matches:
            if '/xsl' not in match and match.endswith('.xml'):
                return f"https://www.sec.gov{match}"
        # Fallback: try any XML that's not an xsl rendering
        for match in xml_matches:
            if '/xsl' not in match:
                return f"https://www.sec.gov{match}"
    except Exception as e:
        logger.debug(f"Index parse error for {base_dir}: {e}")
    return None


def get_form4_filings(symbol: str, days: int = 90, limit: int = 10) -> Optional[List[Dict[str, Any]]]:
    """
    Get recent Form 4 insider filings from SEC EDGAR.

    Args:
        symbol: Stock ticker
        days: How far back to look
        limit: Max number of filings to return

    Returns:
        List of insider transaction dicts
    """
    try:
        filing_dirs = _get_filing_urls_from_atom(symbol)
        if not filing_dirs:
            return None

        cutoff = datetime.now() - timedelta(days=days)
        results = []

        for base_dir in filing_dirs[:3]:
            # Try common names first, then discover from index page
            txs = _parse_form4_xml(f"{base_dir}/form4.xml")
            if not txs:
                txs = _parse_form4_xml(f"{base_dir}/primary_doc.xml")
            if not txs:
                xml_url = _find_xml_in_filing(base_dir)
                if xml_url:
                    txs = _parse_form4_xml(xml_url)

            for tx in txs:
                try:
                    tx_date = datetime.strptime(tx.get('date', ''), '%Y-%m-%d')
                except ValueError:
                    continue
                if tx_date < cutoff:
                    continue

                code = tx.get('code', '')
                results.append({
                    "insider": "",
                    "code": code,
                    "action_label": TX_CODES.get(code, code),
                    "shares": int(tx.get('shares', 0)) if tx.get('shares') else None,
                    "price": float(tx['price']) if tx.get('price') else None,
                    "date": tx.get('date', ''),
                    "source": "sec_edgar",
                })
                if len(results) >= limit:
                    break

            if len(results) >= limit:
                break

        return results if results else None

    except Exception as e:
        logger.warning(f"SEC EDGAR fetch error ({symbol}): {e}")
        return None
