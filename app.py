
import os, sys, subprocess, time, pandas as pd, streamlit as st, traceback, asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Dict
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- FIX: Event loop correto no Windows (evita NotImplementedError no asyncio) ---
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception:
        pass
# -------------------------------------------------------------------------------

# ---------- Instala os navegadores ----------
def ensure_playwright_browsers(engine: str):
    try:
        if engine == "firefox":
            subprocess.run([sys.executable, "-m", "playwright", "install", "firefox"], check=False)
            subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "firefox"], check=False)
        else:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=False)
            subprocess.run([sys.executable, "-m", "playwright", "install", "--with-deps", "chromium"], check=False)
    except Exception as e:
        st.warning(f"Falha ao instalar browsers automaticamente: {e}")

@dataclass
class Settings:
    base_url: str = "https://consultadanfe.com/"
    input_chave: str = (
        "input[name='chave'], "
        "input[name*='chave' i], "
        "input[placeholder*='44' i], "
        "input[type='text']"
    )
    botao_buscar: str = (
        "button:has-text('BUSCAR'), "
        "button:has-text('Buscar'), "
        "a:has-text('BUSCAR'), "
        "a:has-text('Buscar'), "
        "text=/^\s*BUSCAR\s*$/i"
    )
    botao_baixar_xml: str = (
        "button:has-text('Baixar XML'), "
        "a:has-text('Baixar XML')"
    )
    timeout_ms: int = 70000

settings = Settings()

class ConsultaDanfeBot:
    def __init__(self, engine="firefox", headless=True, slow_mo_ms=0, debug=False):
        self.engine = engine
        self.headless = headless
        self.slow_mo_ms = slow_mo_ms
        self.debug = debug
        self.play = self.browser = self.context = self.page = None

    def __enter__(self):
        self.play = sync_playwright().start()
        if self.engine == "firefox":
            self.browser = self.play.firefox.launch(headless=self.headless, slow_mo=self.slow_mo_ms or 0)
        else:
            self.browser = self.play.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
                slow_mo=self.slow_mo_ms or 0
            )
        self.context = self.browser.new_context(accept_downloads=True)
        self.page = self.context.new_page()
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self.context: self.context.close()
            if self.browser: self.browser.close()
        finally:
            if self.play: self.play.stop()

    def log(self, msg):
        if self.debug:
            st.write(f"🛠️ {msg}")

    def abrir(self, url: str = None):
        self.log("Abrindo site…")
        self.page.goto(url or settings.base_url, wait_until="domcontentloaded", timeout=settings.timeout_ms)

    def esperar(self, locator_str: str, timeout=15000):
        self.log(f"Aguardando: {locator_str}")
        self.page.locator(locator_str).first.wait_for(timeout=timeout)

    def processar_chave(self, chave: str) -> Dict:
        try:
            self.abrir()
        except Exception as e:
            return {"chave": chave, "status": "falha", "detalhe": f"Erro ao abrir site: {e}", "trace": traceback.format_exc()}

        preencheu = False
        for sel in [s.strip() for s in settings.input_chave.split(",") if s.strip()]:
            try:
                inp = self.page.locator(sel).first
                inp.fill("")
                inp.type(chave, delay=8)
                preencheu = True
                self.log(f"Preencheu com seletor: {sel}")
                break
            except Exception:
                continue
        if not preencheu:
            return {"chave": chave, "status": "falha", "detalhe": "Campo da chave não localizado."}

        clicou = False
        for sel in [s.strip() for s in settings.botao_buscar.split(",") if s.strip()]:
            try:
                self.log(f"Clicando BUSCAR com seletor: {sel}")
                self.page.locator(sel).first.click(timeout=3000)
                clicou = True
                break
            except Exception:
                continue
        if not clicou:
            try:
                self.page.keyboard.press("Enter")
                clicou = True
                self.log("Disparou Enter como fallback")
            except Exception:
                pass

        try:
            self.esperar(settings.botao_baixar_xml, timeout=30000)
        except Exception:
            try:
                self.page.wait_for_timeout(1000)
                self.page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:
                pass

        for sel in [s.strip() for s in settings.botao_baixar_xml.split(",") if s.strip()]:
            try:
                self.log(f"Tentando clicar em Baixar XML com seletor: {sel}")
                with self.page.expect_download(timeout=25000) as dl_info:
                    self.page.locator(sel).first.click()
                download = dl_info.value
                suggested = download.suggested_filename or f"{chave}.xml"
                tmp_path = os.path.join(str(Path.cwd()), suggested)
                download.save_as(tmp_path)
                with open(tmp_path, "rb") as f:
                    data = f.read()
                try: os.remove(tmp_path)
                except Exception: pass
                return {"chave": chave, "status": "ok", "filename": suggested, "data": data}
            except PlaywrightTimeoutError:
                continue
            except Exception:
                continue

        shot = f"{chave}_resultado.png"
        html = f"{chave}_resultado.html"
        try:
            self.page.screenshot(path=shot, full_page=True)
        except Exception:
            shot = None
        try:
            content = self.page.content()
            with open(html, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception:
            html = None
        return {
            "chave": chave,
            "status": "sem_download",
            "detalhe": "Não localizei 'Baixar XML' (pode ser bloqueio a headless/engine).",
            "screenshot": shot,
            "html": html
        }

st.set_page_config(page_title="Consulta & Download XML — consultadanfe.com", layout="wide")
st.title("🧾 Consulta & Download XML — consultadanfe.com")
st.caption("Cole várias chaves (uma por linha). Se algo falhar, ative DEBUG para ver detalhes e baixar evidências.")

with st.sidebar:
    st.header("Configurações")
    engine = st.radio("Navegador", options=["firefox", "chromium"], index=0, help="Se Firefox falhar, troque para Chromium.")
    headless = st.checkbox("Headless (sem abrir janela)", value=False)
    slow_mo_ms = st.number_input("Slow motion (ms)", value=0, step=50, min_value=0)
    debug = st.checkbox("DEBUG detalhado (logs e rastreio)", value=True)

st.subheader("Chaves de acesso (uma por linha)")
txt = st.text_area("Cole aqui", height=160, placeholder="44 dígitos por linha…")
chaves = [c.strip() for c in txt.splitlines() if c.strip()]
go = st.button("🚀 Consultar & Baixar XML")

if "resultados" not in st.session_state: st.session_state.resultados = []

if go and not chaves:
    st.warning("Informe pelo menos 1 chave.")
elif go:
    ensure_playwright_browsers(engine)
    resultados = []
    try:
        with ConsultaDanfeBot(engine=engine, headless=headless, slow_mo_ms=slow_mo_ms, debug=debug) as bot:
            for chave in chaves:
                r = bot.processar_chave(chave)
                resultados.append(r)
    except Exception as e:
        st.error("Dramaturgo da Falha:")
        st.exception(e)
    else:
        st.session_state.resultados = resultados

if st.session_state.get("resultados"):
    st.subheader("Resultados")
    linhas = []
    for r in st.session_state.resultados:
        base = {"chave": r.get("chave"), "status": r.get("status")}
        if r.get("status") == "ok": base["arquivo"] = r.get("filename")
        else: base["detalhe"] = r.get("detalhe")
        linhas.append(base)
    st.dataframe(pd.DataFrame(linhas), use_container_width=True)

    st.markdown("### Baixar resultados / evidências")
    for r in st.session_state.resultados:
        if r.get("status") == "ok" and r.get("data"):
            st.download_button(
                label=f"⬇️ Baixar {r['filename']}",
                data=r["data"],
                file_name=r["filename"],
                mime="application/xml"
            )
        else:
            if r.get("screenshot"):
                with open(r["screenshot"], "rb") as f:
                    st.download_button(
                        label=f"📷 Screenshot {r['chave']}",
                        data=f.read(),
                        file_name=r["screenshot"],
                        mime="image/png"
                    )
            if r.get("html"):
                with open(r["html"], "rb") as f:
                    st.download_button(
                        label=f"🧩 HTML {r['chave']}",
                        data=f.read(),
                        file_name=r["html"],
                        mime="text/html"
                    )
