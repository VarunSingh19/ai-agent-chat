"""WebSocket `/v1/inbox/stream` authenticating via first JSON frame (Architecture.md §8)."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from pdagent.auth.token import TokenVerifier

router = APIRouter(tags=["inbox-ws"])


@router.websocket("/v1/inbox/stream")
async def inbox_websocket_stream(websocket: WebSocket) -> None:
    """Authenticate via the first WebSocket JSON frame (never URL
    query params) and stream updates."""
    if "token" in websocket.query_params:
        await websocket.close(code=1008, reason="Token in URL query string is forbidden")
        return

    await websocket.accept()
    try:
        first_frame = await websocket.receive_json()
        raw_token = str(first_frame.get("token", "")) if isinstance(first_frame, dict) else ""
        verifier: TokenVerifier = getattr(websocket.app.state, "token_verifier", TokenVerifier())
        principal = await verifier.verify_token(raw_token)
        if principal.role not in ("pm_member", "org_admin"):
            await websocket.send_json({"event": "error", "code": "AUTH_FORBIDDEN"})
            await websocket.close(code=1008)
            return

        await websocket.send_json(
            {
                "event": "authenticated",
                "org_id": str(principal.org_id),
                "role": principal.role,
            }
        )
    except WebSocketDisconnect:
        return
    except Exception:
        await websocket.close(code=1008)
