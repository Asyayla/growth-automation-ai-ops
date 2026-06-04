"""
ai/claude_client.py
--------------------
Anthropic Claude API için temiz, yeniden kullanılabilir wrapper.
  - Retry mekanizması (exponential backoff)
  - Rate limit yönetimi
  - JSON parse güvenliği
  - Mock mod (API key yoksa test verisi döner)

Kullanım:
    from ai.claude_client import ClaudeClient
    client = ClaudeClient()
    response = client.complete(system_prompt, user_prompt)
    data = client.complete_json(system_prompt, user_prompt)
"""

import json
import time
import re
from typing import Optional

try:
    import anthropic
    _HAS_ANTHROPIC = True
except ImportError:
    _HAS_ANTHROPIC = False

from utils.config import config
from utils.logger import get_logger

log = get_logger()


class ClaudeAPIError(Exception):
    """API çağrısında kurtarılamayan hata."""
    pass


class ClaudeClient:
    """
    Claude API wrapper.

    API key yoksa veya mock=True ise _mock_response() çağrılır;
    pipeline test edilebilir kalır.
    """

    MAX_RETRIES   = 3
    RETRY_DELAYS  = [1, 3, 7]   # saniye — exponential backoff

    def __init__(self, mock: bool = False):
        self.mock  = mock or not config.anthropic_api_key
        self.model = config.claude_model

        if self.mock:
            log.warning("⚠️  ClaudeClient MOCK modda çalışıyor (gerçek API çağrısı yapılmıyor)")
            self._client = None
        else:
            if not _HAS_ANTHROPIC:
                raise ImportError(
                    "anthropic paketi yüklü değil. "
                    "Çalıştır: pip install anthropic"
                )
            self._client = anthropic.Anthropic(api_key=config.anthropic_api_key)
            log.debug(f"✅ ClaudeClient hazır → model: {self.model}")

    # ─────────────────────────────────────────────────────────────────────────
    #  ANA METOTLAR
    # ─────────────────────────────────────────────────────────────────────────

    def complete(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = None,
        temperature: float = None,
    ) -> str:
        """
        Tek bir mesaj gönderir, ham metin yanıtı döner.

        Args:
            system_prompt : Claude'a verilecek rol/kural tanımı
            user_prompt   : Kullanıcı mesajı / veri
            max_tokens    : Yanıt token limiti (varsayılan: config'den)
            temperature   : Yaratıcılık katsayısı (varsayılan: config'den)

        Returns:
            str: Claude'un yanıt metni

        Raises:
            ClaudeAPIError: Tüm retry'lar tükendikten sonra
        """
        if self.mock:
            return self._mock_response(user_prompt)

        _max_tokens  = max_tokens  or config.ai_max_tokens
        _temperature = temperature or config.ai_temperature

        last_error: Optional[Exception] = None

        for attempt in range(self.MAX_RETRIES):
            try:
                response = self._client.messages.create(
                    model=self._model_for_api(),
                    max_tokens=_max_tokens,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                # Yanıt içeriğini çıkar
                text = response.content[0].text if response.content else ""
                log.debug(
                    f"API yanıtı alındı | "
                    f"tokens: {response.usage.input_tokens}→{response.usage.output_tokens}"
                )
                return text

            except Exception as e:
                last_error = e
                error_str  = str(e).lower()

                # Rate limit — bekle ve tekrar dene
                if "rate_limit" in error_str or "429" in error_str:
                    wait = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                    log.warning(f"⏳ Rate limit — {wait}s bekleniyor (deneme {attempt+1}/{self.MAX_RETRIES})")
                    time.sleep(wait)
                    continue

                # Geçici sunucu hatası — bekle ve tekrar dene
                if any(code in error_str for code in ["500", "529", "overloaded", "timeout"]):
                    wait = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                    log.warning(f"🔄 Sunucu hatası ({e}) — {wait}s sonra tekrar (deneme {attempt+1})")
                    time.sleep(wait)
                    continue

                # Diğer hatalar — direkt fırlat
                log.error(f"❌ API hatası (kurtarılamaz): {e}")
                raise ClaudeAPIError(f"API çağrısı başarısız: {e}") from e

        raise ClaudeAPIError(
            f"Maksimum retry sayısına ulaşıldı ({self.MAX_RETRIES}). "
            f"Son hata: {last_error}"
        )

    def complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = None,
    ) -> dict:
        """
        Claude'dan JSON yanıt ister, güvenli şekilde parse eder.

        Prompt'ta JSON istenmesi gerekir — bu metot sadece parse güvenliğini sağlar.
        Parse başarısız olursa {"error": "...", "raw": "..."} döner.

        Returns:
            dict: Parse edilmiş JSON yanıtı
        """
        raw = self.complete(system_prompt, user_prompt, max_tokens=max_tokens)

        try:
            return self._safe_json_parse(raw)
        except json.JSONDecodeError as e:
            log.error(f"JSON parse hatası: {e}\nHam yanıt: {raw[:300]}")
            return {"error": f"JSON parse hatası: {e}", "raw": raw}

    # ─────────────────────────────────────────────────────────────────────────
    #  YARDIMCI METOTLAR
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _safe_json_parse(text: str) -> dict:
        """
        Claude bazen JSON'u markdown code block içine koyar.
        ```json ... ``` veya ``` ... ``` bloklarını soyar, sonra parse eder.
        """
        text = text.strip()

        # Markdown code block varsa içini al
        md_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
        if md_match:
            text = md_match.group(1).strip()

        # Hâlâ { ile başlamıyorsa ilk { bul
        if not text.startswith("{"):
            brace_idx = text.find("{")
            if brace_idx != -1:
                text = text[brace_idx:]

        return json.loads(text)

    def _model_for_api(self) -> str:
        """
        Config'deki model adını API'nin beklediği formata çevirir.
        claude-sonnet-4-20250514  →  olduğu gibi gönderilir
        """
        return self.model

    @staticmethod
    def _mock_response(user_prompt: str) -> str:
        """
        Akıllı mock: mock_data motoru üzerinden şirkete özgü enrichment üretir.
        Prompt içindeki Şirket / Kişi / Ünvan / Kıdem satırlarını parse eder.
        """
        from ai.mock_data import build_enrichment_mock

        # Prompt'tan yapılandırılmış alanları çıkar
        import re
        def _extract(label: str) -> str:
            m = re.search(rf"{label}\s*:\s*(.+)", user_prompt)
            return m.group(1).strip() if m else ""

        company   = _extract("Şirket")   or _extract("Company") or "Bilinmiyor"
        full_name = _extract("Ad Soyad")  or _extract("Full Name") or ""
        title     = _extract("Ünvan")     or _extract("Title") or ""
        seniority = _extract("Kıdem")     or _extract("Seniority") or "Mid"

        result = build_enrichment_mock(
            company   = company,
            full_name = full_name,
            title     = title,
            seniority = seniority,
        )
        return json.dumps(result, ensure_ascii=False)

    def health_check(self) -> bool:
        """API bağlantısını test eder. True = sağlıklı."""
        if self.mock:
            log.info("🔧 Mock mod — health check atlandı")
            return True
        try:
            result = self.complete(
                system_prompt="Sadece 'OK' yaz.",
                user_prompt="Test",
                max_tokens=5,
            )
            ok = "ok" in result.lower()
            log.info(f"API health check: {'✅ OK' if ok else '⚠️  Beklenmedik yanıt'}")
            return ok
        except ClaudeAPIError as e:
            log.error(f"API health check başarısız: {e}")
            return False
