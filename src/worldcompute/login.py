"""Public OAuth client: PKCE S256, loopback callback, in-memory credentials."""
import asyncio
import base64
import hashlib
import secrets
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
from .session import ControlsError

CLIENT_ID = 'world-compute-python'
REDIRECT = 'http://127.0.0.1:8765/callback'


async def authorize(http, origin, *, physical=False, open_browser=True, timeout=180):
    metadata = await http.get('/.well-known/oauth-protected-resource/mcp')
    metadata.raise_for_status()
    resource = metadata.json()['resource']
    discovery = await http.get('/.well-known/oauth-authorization-server/oauth')
    discovery.raise_for_status()
    issuer = discovery.json()['issuer']
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    future = asyncio.get_running_loop().create_future()

    async def callback(reader, writer):
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            parts = line.decode('ascii').split()
            target = urlparse(parts[1]) if len(parts) == 3 and parts[0] == 'GET' else None
            query = parse_qs(target.query) if target else {}
            valid = (target and target.path == '/callback' and query.get('state') == [state]
                     and query.get('iss') == [issuer])
            code = query.get('code', [])
            if valid and len(code) == 1 and not future.done():
                future.set_result(code[0])
                status, message = '200 OK', 'Authorized. Return to your terminal.'
            else:
                if valid and query.get('error') and not future.done():
                    future.set_exception(ControlsError('Authorization denied'))
                status, message = '400 Bad Request', 'Invalid or denied authorization.'
            body = message.encode()
            writer.write(f'HTTP/1.1 {status}\r\nContent-Type: text/plain\r\nCache-Control: no-store\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
            await writer.drain()
        except (ValueError, UnicodeError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(callback, '127.0.0.1', 8765, limit=8192)
    url = origin+'/oauth/auth?'+urlencode({'client_id':CLIENT_ID, 'response_type':'code',
        'redirect_uri':REDIRECT, 'scope':'robot:read simulator:control offline_access'+(' robot:control' if physical else ''),
        'resource':resource, 'state':state, 'code_challenge':challenge, 'code_challenge_method':'S256'})
    try:
        print('Sign in to World Compute:', url)
        if open_browser:
            webbrowser.open(url)
        async with server:
            code = await asyncio.wait_for(future, timeout)
        response = await http.post('/oauth/token', data={'grant_type':'authorization_code',
            'client_id':CLIENT_ID,'redirect_uri':REDIRECT,'code':code,
            'code_verifier':verifier,'resource':resource})
        if response.status_code != 200:
            raise ControlsError('Authorization exchange failed; start login again')
        tokens = response.json()
        tokens['_resource'] = resource
        return tokens
    finally:
        server.close()
        await server.wait_closed()
