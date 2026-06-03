"""
Outlook Email Client - Microsoft Graph Integration

Handles:
- OAuth2 token management (acquire, refresh, scope isolation)
- Send emails via Outlook
- Return Graph API message IDs for idempotency tracking
- Inbox monitoring with delta queries (only new/changed emails)
- Parse email metadata without storing raw content

Usage:
    client = OutlookEmailClient(
        client_id="...",
        client_secret="...",
        tenant_id="...",
    )
    
    # Send email
    result = client.send_email(
        user_id="user@company.com",
        to=["recipient@example.com"],
        subject="Job Opportunity",
        body="...",
        idempotency_key="email-001",  # For idempotency
    )
    # Returns: {"message_id": "msg-graph-001", "sent_at": datetime}
    
    # Get new/changed emails (delta)
    emails = client.get_inbox_delta(
        user_id="user@company.com",
        delta_token="prev-token",
    )
    # Returns: list of EmailMetadata + new delta_token
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from enum import Enum
import json
import requests
from abc import ABC, abstractmethod


# ============================================================================
# ENUMS & DATA CLASSES
# ============================================================================

class EmailDirection(str, Enum):
    """Email direction"""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


@dataclass
class EmailMetadata:
    """Email metadata (no raw content stored)"""
    message_id: str  # Graph API ID
    subject: str
    from_email: str
    to_emails: List[str]
    received_at: datetime
    direction: EmailDirection
    is_read: bool
    importance: str  # low, normal, high
    
    # Conversation tracking
    conversation_id: Optional[str] = None
    conversation_index: Optional[str] = None
    in_reply_to: Optional[str] = None  # Original message ID if this is a reply
    
    # Parsing hints
    body_preview: Optional[str] = None  # First 256 chars (for AI parsing)
    has_attachments: bool = False


@dataclass
class SendEmailResult:
    """Result of sending email"""
    message_id: str  # Graph API ID (use for idempotency checking)
    sent_at: datetime
    status: str  # "sent", "queued", "failed"
    error: Optional[str] = None


@dataclass
class InboxDeltaResult:
    """Delta query result"""
    emails: List[EmailMetadata]
    delta_token: str  # Pass to next delta query
    has_more_changes: bool


# ============================================================================
# TOKEN MANAGEMENT
# ============================================================================

class TokenStore(ABC):
    """Abstract token storage (implement for your backend)"""
    
    @abstractmethod
    def get_token(self, user_id: str) -> Optional[str]:
        """Get stored access token"""
        pass
    
    @abstractmethod
    def set_token(self, user_id: str, token: str, expires_at: datetime):
        """Store access token with expiration"""
        pass
    
    @abstractmethod
    def get_refresh_token(self, user_id: str) -> Optional[str]:
        """Get stored refresh token"""
        pass
    
    @abstractmethod
    def set_refresh_token(self, user_id: str, token: str):
        """Store refresh token"""
        pass
    
    @abstractmethod
    def get_delta_token(self, user_id: str) -> Optional[str]:
        """Get last delta token for inbox polling"""
        pass
    
    @abstractmethod
    def set_delta_token(self, user_id: str, token: str):
        """Store delta token for next poll"""
        pass


class InMemoryTokenStore(TokenStore):
    """Simple in-memory token store (for testing only)"""
    
    def __init__(self):
        self._tokens: Dict[str, Dict[str, Any]] = {}
    
    def get_token(self, user_id: str) -> Optional[str]:
        data = self._tokens.get(user_id)
        if not data:
            return None
        
        # Check expiration
        if data.get("expires_at") and data["expires_at"] < datetime.now(timezone.utc):
            return None
        
        return data.get("token")
    
    def set_token(self, user_id: str, token: str, expires_at: datetime):
        if user_id not in self._tokens:
            self._tokens[user_id] = {}
        self._tokens[user_id]["token"] = token
        self._tokens[user_id]["expires_at"] = expires_at
    
    def get_refresh_token(self, user_id: str) -> Optional[str]:
        return self._tokens.get(user_id, {}).get("refresh_token")
    
    def set_refresh_token(self, user_id: str, token: str):
        if user_id not in self._tokens:
            self._tokens[user_id] = {}
        self._tokens[user_id]["refresh_token"] = token
    
    def get_delta_token(self, user_id: str) -> Optional[str]:
        return self._tokens.get(user_id, {}).get("delta_token")
    
    def set_delta_token(self, user_id: str, token: str):
        if user_id not in self._tokens:
            self._tokens[user_id] = {}
        self._tokens[user_id]["delta_token"] = token


# ============================================================================
# OUTLOOK EMAIL CLIENT
# ============================================================================

class OutlookEmailClient:
    """
    Microsoft Graph API client for Outlook email operations
    
    Scope: https://graph.microsoft.com/.default (for testing)
    Production: Use specific scopes:
    - Mail.Send (send emails)
    - Mail.Read (read emails)
    - Mail.ReadWrite (read + write)
    """
    
    GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
    OAUTH_ENDPOINT = "https://login.microsoftonline.com"
    
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        tenant_id: str = "common",
        token_store: Optional[TokenStore] = None,
    ):
        """
        Initialize Outlook client
        
        Args:
            client_id: Azure AD application ID
            client_secret: Azure AD application secret
            tenant_id: Azure AD tenant (default: "common" for multi-tenant)
            token_store: Token storage backend (default: in-memory)
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.token_store = token_store or InMemoryTokenStore()
        self.session = requests.Session()
    
    # ========================================================================
    # OAUTH2 TOKEN MANAGEMENT
    # ========================================================================
    
    def get_authorization_url(self, redirect_uri: str, state: Optional[str] = None) -> str:
        """
        Get OAuth2 authorization URL for user login
        
        Usage in web app:
            url = client.get_authorization_url(redirect_uri="https://app.com/callback")
            # Redirect user to url
        """
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "Mail.Send Mail.Read offline_access",
            "state": state or "state123",
        }
        
        return f"{self.OAUTH_ENDPOINT}/{self.tenant_id}/oauth2/v2.0/authorize?" + \
               "&".join(f"{k}={v}" for k, v in params.items())
    
    def exchange_code_for_token(
        self,
        code: str,
        redirect_uri: str,
        user_id: str,
    ) -> str:
        """
        Exchange authorization code for access token
        
        Called in OAuth2 callback
        """
        url = f"{self.OAUTH_ENDPOINT}/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
            "scope": "Mail.Send Mail.Read offline_access",
        }
        
        response = requests.post(url, data=data)
        response.raise_for_status()
        
        token_data = response.json()
        access_token = token_data["access_token"]
        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in", 3600)
        
        # Store tokens
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        self.token_store.set_token(user_id, access_token, expires_at)
        if refresh_token:
            self.token_store.set_refresh_token(user_id, refresh_token)
        
        return access_token
    
    def _get_valid_token(self, user_id: str) -> str:
        """Get valid access token (refresh if expired)"""
        token = self.token_store.get_token(user_id)
        
        if token:
            return token
        
        # Try refresh
        refresh_token = self.token_store.get_refresh_token(user_id)
        if not refresh_token:
            raise ValueError(f"No valid token for user {user_id}")
        
        return self._refresh_token(user_id, refresh_token)
    
    def _refresh_token(self, user_id: str, refresh_token: str) -> str:
        """Refresh access token"""
        url = f"{self.OAUTH_ENDPOINT}/{self.tenant_id}/oauth2/v2.0/token"
        
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "scope": "Mail.Send Mail.Read offline_access",
        }
        
        response = requests.post(url, data=data)
        response.raise_for_status()
        
        token_data = response.json()
        access_token = token_data["access_token"]
        new_refresh_token = token_data.get("refresh_token", refresh_token)
        expires_in = token_data.get("expires_in", 3600)
        
        # Store new tokens
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        self.token_store.set_token(user_id, access_token, expires_at)
        if new_refresh_token:
            self.token_store.set_refresh_token(user_id, new_refresh_token)
        
        return access_token
    
    # ========================================================================
    # SEND EMAIL
    # ========================================================================
    
    def send_email(
        self,
        user_id: str,
        to: List[str],
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        html_body: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> SendEmailResult:
        """
        Send email via Outlook
        
        Args:
            user_id: User's email address (user@company.com)
            to: List of recipient emails
            subject: Email subject
            body: Plain text body
            cc: CC recipients
            bcc: BCC recipients
            html_body: HTML version of body
            idempotency_key: Idempotency key (prevents duplicates)
        
        Returns:
            SendEmailResult with message_id for tracking
        """
        token = self._get_valid_token(user_id)
        
        # Build email
        message = {
            "subject": subject,
            "body": {
                "contentType": "HTML" if html_body else "text",
                "content": html_body or body,
            },
            "toRecipients": [{"emailAddress": {"address": email}} for email in to],
            "ccRecipients": [{"emailAddress": {"address": email}} for email in (cc or [])],
            "bccRecipients": [{"emailAddress": {"address": email}} for email in (bcc or [])],
        }
        
        # Send
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        
        url = f"{self.GRAPH_API_BASE}/users/{user_id}/sendMail"
        
        response = requests.post(
            url,
            json={"message": message, "saveToSentItems": True},
            headers=headers,
        )
        
        try:
            response.raise_for_status()
            
            # Microsoft doesn't return message ID in send response
            # It's available if you check sent items afterwards
            return SendEmailResult(
                message_id="pending",  # Will be fetched from sent items
                sent_at=datetime.now(timezone.utc),
                status="sent",
            )
        except requests.exceptions.RequestException as e:
            return SendEmailResult(
                message_id="",
                sent_at=datetime.now(timezone.utc),
                status="failed",
                error=str(e),
            )
    
    # ========================================================================
    # INBOX POLLING (DELTA QUERIES)
    # ========================================================================
    
    def get_inbox_delta(
        self,
        user_id: str,
        delta_token: Optional[str] = None,
    ) -> InboxDeltaResult:
        """
        Get new/changed emails since last delta query (Graph API delta queries)
        
        Delta queries are efficient because:
        - Only return changed emails (not entire inbox)
        - Stores position via delta_token
        - Supports incremental sync
        
        Usage:
            # First call (no token)
            result = client.get_inbox_delta(user_id)
            
            # Store result.delta_token for next call
            
            # Next call (with token) - only gets changes
            result = client.get_inbox_delta(user_id, delta_token=prev_token)
        
        Returns:
            InboxDeltaResult with emails + new delta_token
        """
        token = self._get_valid_token(user_id)
        
        # Use stored delta token if not provided
        if not delta_token:
            delta_token = self.token_store.get_delta_token(user_id)
        
        # Build URL
        url = f"{self.GRAPH_API_BASE}/users/{user_id}/mailFolders/inbox/messages/delta"
        
        params = {
            "$select": "id,subject,from,toRecipients,receivedDateTime,isRead,importance,bodyPreview,hasAttachments,conversationId,conversationIndex,parentMessageId",
            "$top": 50,
        }
        
        if delta_token:
            params["$deltaToken"] = delta_token
        
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(url, params=params, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        
        # Parse emails
        emails = []
        for item in data.get("value", []):
            email = self._parse_email_metadata(item)
            if email:
                emails.append(email)
        
        # Get new delta token
        new_delta_token = data.get("@odata.deltaLink", "").split("$deltaToken=")[-1] if "$deltaToken=" in data.get("@odata.deltaLink", "") else delta_token
        
        # Store new delta token
        if new_delta_token:
            self.token_store.set_delta_token(user_id, new_delta_token)
        
        return InboxDeltaResult(
            emails=emails,
            delta_token=new_delta_token or "",
            has_more_changes=False,  # Could check @odata.nextLink
        )
    
    def _parse_email_metadata(self, item: Dict[str, Any]) -> Optional[EmailMetadata]:
        """Parse Graph API email item into EmailMetadata"""
        try:
            received_at = datetime.fromisoformat(
                item.get("receivedDateTime", "").replace("Z", "+00:00")
            )
            
            from_email = item.get("from", {}).get("emailAddress", {}).get("address", "")
            
            to_emails = [
                recipient.get("emailAddress", {}).get("address", "")
                for recipient in item.get("toRecipients", [])
            ]
            
            return EmailMetadata(
                message_id=item.get("id", ""),
                subject=item.get("subject", ""),
                from_email=from_email,
                to_emails=to_emails,
                received_at=received_at,
                direction=EmailDirection.INBOUND,
                is_read=item.get("isRead", False),
                importance=item.get("importance", "normal"),
                conversation_id=item.get("conversationId"),
                conversation_index=item.get("conversationIndex"),
                in_reply_to=item.get("parentMessageId"),
                body_preview=item.get("bodyPreview", "")[:256],
                has_attachments=item.get("hasAttachments", False),
            )
        except Exception as e:
            print(f"⚠️ Failed to parse email metadata: {e}")
            return None
    
    # ========================================================================
    # GET EMAIL CONTENT
    # ========================================================================
    
    def get_email_body(self, user_id: str, message_id: str) -> Optional[str]:
        """
        Get full email body for parsing
        
        Call only for replies that need parsing (not all emails)
        """
        token = self._get_valid_token(user_id)
        
        url = f"{self.GRAPH_API_BASE}/users/{user_id}/messages/{message_id}"
        
        headers = {"Authorization": f"Bearer {token}"}
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        data = response.json()
        
        # Return body
        body_data = data.get("body", {})
        content = body_data.get("content", "")
        
        return content or None


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == "__main__":
    client = OutlookEmailClient(
        client_id="YOUR_CLIENT_ID",
        client_secret="YOUR_CLIENT_SECRET",
        tenant_id="common",
    )
    
    print("✅ OutlookEmailClient ready")
    print("   Usage: Send emails, monitor inbox with delta queries")
