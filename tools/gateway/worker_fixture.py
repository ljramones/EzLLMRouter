"""Network-denial probe for the disposable worker harness only."""

import asyncio

import httpx

from worker import choice_b_worker as runtime


class FixtureWorker(runtime.Worker):
    async def _raw_probe(self):
        raw = {
            "model": "probe.invalid",
            "messages": [
                {"role": "system", "content": "Synthetic."},
                {"role": "user", "content": "Direct worker egress probe."},
            ],
        }
        try:
            async with httpx.AsyncClient(
                transport=httpx.AsyncHTTPTransport(retries=0, trust_env=False),
                trust_env=False,
                timeout=1,
            ) as client:
                response = await client.post(
                    runtime.PROVIDER_URL,
                    json=raw,
                    headers={"X-EzLLMRouter-Attempt": "probe.raw.choice-b"},
                )
            return {"probe": "raw_worker_direct_provider", "status": response.status_code}
        except Exception as exc:
            return {"probe": "raw_worker_direct_provider", "error_type": type(exc).__name__}

    def dispatch(self, envelope):
        if envelope == {"kind": "raw_egress_probe"}:
            future = asyncio.run_coroutine_threadsafe(self._raw_probe(), self.loop)
            try:
                return future.result(timeout=5)
            except BaseException:
                future.cancel()
                raise
        return super().dispatch(envelope)


if __name__ == "__main__":
    runtime.Worker = FixtureWorker
    runtime.main()
