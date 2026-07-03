"""
SMTP Email Sender Module for Daily Investment Report
Supports multiple providers: QQ Mail, Gmail, Outlook
"""

import os
import smtplib
import ssl
import json
import logging
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
from datetime import datetime

logger = logging.getLogger(__name__)
from pathlib import Path


# Provider configurations
PROVIDERS = {
    'qq': {
        'smtp_server': 'smtp.qq.com',
        'smtp_port': 465,
        'use_ssl': True
    },
    'gmail': {
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': 587,
        'use_ssl': False  # Uses STARTTLS
    },
    'outlook': {
        'smtp_server': 'smtp-mail.outlook.com',
        'smtp_port': 587,
        'use_ssl': False  # Uses STARTTLS (requires OAuth2)
    },
    '163': {
        'smtp_server': 'smtp.163.com',
        'smtp_port': 465,
        'use_ssl': True
    }
}


class EmailSender:
    """Email sender class with retry support and multi-provider support"""

    def __init__(self, config_path=None):
        """
        Initialize email sender with configuration

        Args:
            config_path: Path to config.json file
        """
        if config_path is None:
            config_path = Path(__file__).resolve().parent.parent / "config.json"

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        email_config = config['email_service']
        self.provider = email_config.get('provider', 'custom')

        # Use provider defaults if available, otherwise use config values
        if self.provider in PROVIDERS:
            provider_defaults = PROVIDERS[self.provider]
            self.smtp_server = email_config.get('smtp_server', provider_defaults['smtp_server'])
            self.smtp_port = email_config.get('smtp_port', provider_defaults['smtp_port'])
            self.use_ssl = email_config.get('use_ssl', provider_defaults['use_ssl'])
        else:
            self.smtp_server = email_config['smtp_server']
            self.smtp_port = email_config['smtp_port']
            self.use_ssl = email_config.get('use_ssl', False)

        self.sender_email = email_config['sender_email']
        self.sender_name = email_config['sender_name']
        self.app_password = os.environ.get('SMTP_PASSWORD') or email_config.get('app_password', '')

        # Retry settings
        self.max_retries = 3
        self.retry_delay = 2  # seconds

    def _create_connection(self):
        """
        Create SMTP connection based on provider settings

        Returns:
            SMTP or SMTP_SSL connection
        """
        if self.use_ssl:
            # SSL connection (QQ Mail, 163 Mail)
            context = ssl.create_default_context()
            return smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context)
        else:
            # STARTTLS connection (Gmail, Outlook)
            return smtplib.SMTP(self.smtp_server, self.smtp_port)

    def send(self, to_email, subject, html_content, plain_text=None):
        """
        Send HTML email to recipient

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML body content
            plain_text: Optional plain text version

        Returns:
            bool: True if sent successfully

        Raises:
            Exception: If all retries fail
        """
        msg = MIMEMultipart('alternative')
        msg['From'] = formataddr((self.sender_name, self.sender_email))
        msg['To'] = to_email
        msg['Subject'] = subject
        msg['Date'] = datetime.now().strftime('%a, %d %b %Y %H:%M:%S %z')

        # Add plain text part if provided
        if plain_text:
            text_part = MIMEText(plain_text, 'plain', 'utf-8')
            msg.attach(text_part)

        # Add HTML part
        html_part = MIMEText(html_content, 'html', 'utf-8')
        msg.attach(html_part)

        # Send with retry
        last_error = None
        for attempt in range(self.max_retries):
            try:
                server = self._create_connection()

                try:
                    if not self.use_ssl:
                        # STARTTLS connection needs EHLO and starttls()
                        server.ehlo()
                        server.starttls()
                        server.ehlo()

                    server.login(self.sender_email, self.app_password)
                    server.sendmail(self.sender_email, to_email, msg.as_string())

                    logger.info(f"Email sent to {to_email}")
                    return True

                finally:
                    server.quit()

            except smtplib.SMTPAuthenticationError as e:
                logger.error(f"Authentication failed: {e}")
                raise Exception("SMTP authentication failed. Check your email and app password.")

            except smtplib.SMTPException as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1} failed: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))  # Exponential backoff

            except Exception as e:
                last_error = e
                logger.warning(f"Unexpected error on attempt {attempt + 1}: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (2 ** attempt))

        raise Exception(f"Failed to send email after {self.max_retries} attempts: {last_error}")


def test_connection(config_path=None):
    """
    Test SMTP connection without sending email

    Returns:
        bool: True if connection successful
    """
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.json"

    with open(config_path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    email_config = config['email_service']
    provider = email_config.get('provider', 'custom')

    # Get provider settings
    if provider in PROVIDERS:
        provider_defaults = PROVIDERS[provider]
        smtp_server = email_config.get('smtp_server', provider_defaults['smtp_server'])
        smtp_port = email_config.get('smtp_port', provider_defaults['smtp_port'])
        use_ssl = email_config.get('use_ssl', provider_defaults['use_ssl'])
    else:
        smtp_server = email_config['smtp_server']
        smtp_port = email_config['smtp_port']
        use_ssl = email_config.get('use_ssl', False)

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context) as server:
                server.login(email_config['sender_email'], os.environ.get('SMTP_PASSWORD') or email_config.get('app_password', ''))
        else:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(email_config['sender_email'], os.environ.get('SMTP_PASSWORD') or email_config.get('app_password', ''))

        logger.info(f"SMTP connection test successful ({provider})")
        return True

    except Exception as e:
        logger.error(f"SMTP connection test failed: {e}")
        return False


if __name__ == "__main__":
    # Test the connection
    print("Testing SMTP connection...")
    test_connection()
