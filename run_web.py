import uvicorn
import os
import subprocess
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# Auto-detect system proxy for yfinance / requests (macOS system proxy)
if not os.environ.get("HTTPS_PROXY"):
    try:
        r = subprocess.run(
            ["networksetup", "-getsecurewebproxy", "Wi-Fi"],
            capture_output=True, text=True, timeout=3,
        )
        enabled = "Enabled: Yes" in r.stdout
        if enabled:
            host = port = ""
            for line in r.stdout.splitlines():
                if line.startswith("Server:"):
                    host = line.split(":", 1)[1].strip()
                elif line.startswith("Port:"):
                    port = line.split(":", 1)[1].strip()
            proxy = f"http://{host}:{port}"
            os.environ.setdefault("HTTP_PROXY", proxy)
            os.environ.setdefault("HTTPS_PROXY", proxy)
    except Exception:
        pass

# Bypass proxy for AKShare data sources (eastmoney)
_no_proxy = os.environ.get("NO_PROXY", "")
_eastmoney_domains = ".eastmoney.com,.push2.eastmoney.com,.push2his.eastmoney.com,.push2delay.eastmoney.com"
if _no_proxy:
    os.environ["NO_PROXY"] = f"{_no_proxy},{_eastmoney_domains}"
else:
    os.environ["NO_PROXY"] = _eastmoney_domains


def main():
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("WEB_PORT", "8000"))

    from investbrief.web.app import create_app
    app = create_app()
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
