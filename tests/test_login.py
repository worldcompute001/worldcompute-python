import asyncio
import hashlib
import base64
from urllib.parse import urlparse, parse_qs, urlencode
import httpx
from worldcompute.login import authorize

async def test_login_checks_callback_state_and_pkce(monkeypatch):
    urls=[];monkeypatch.setattr('webbrowser.open',lambda url:urls.append(url))
    observed={}
    def exchange(req):
        if req.method == "GET":
            return httpx.Response(200,json={"resource":"https://issuer.test/mcp","issuer":"https://issuer.test/oauth"})
        data=parse_qs(req.content.decode());observed.update(data)
        return httpx.Response(200,json={'access_token':'token','refresh_token':'refresh','expires_in':900})
    async with httpx.AsyncClient(base_url='https://wc.test',transport=httpx.MockTransport(exchange)) as http:
        task=asyncio.create_task(authorize(http,'https://wc.test',timeout=5))
        try:
            for _ in range(50):
                if urls:break
                await asyncio.sleep(.01)
            query=parse_qs(urlparse(urls[0]).query)
            assert query['client_id']==['world-compute-python']
            assert 'robot:control' not in query['scope'][0]
            async with httpx.AsyncClient(trust_env=False) as callback:
                bad=await callback.get('http://127.0.0.1:8765/callback',params={'state':'wrong','iss':'https://issuer.test/oauth','code':'bad'})
                assert bad.status_code==400;assert not task.done()
                ok=await callback.get('http://127.0.0.1:8765/callback',params={'state':query['state'][0],'iss':'https://issuer.test/oauth','code':'good'})
                assert ok.status_code==200
            assert (await task)['access_token']=='token'
            challenge=base64.urlsafe_b64encode(hashlib.sha256(observed['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
            assert query['code_challenge']==[challenge]
            assert observed['resource']==['https://issuer.test/mcp'];assert observed['code']==['good'];assert 'client_secret' not in observed
        finally:
            if not task.done():
                task.cancel()
                try:await task
                except asyncio.CancelledError:pass
