import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# CEP / Loja
CEP = "90560-005"

# Banco de dados na raiz do projeto
DB_PATH = os.path.join(BASE_DIR, "atacado_precos.db")

# Playwright
HEADLESS = True
NAV_TIMEOUT_MS = 45_000
SLOW_MO_MS = 0

USAR_SESSAO_SALVA = True
PERFIL_NAVEGADOR_DIR = os.path.join(BASE_DIR, "credentials", "perfil_atacadao")

MAX_PAGINAS_POR_CATEGORIA = 5

# Google Sheets
# ATENÇÃO: GOOGLE_SHEETS_SPREADSHEET_ID vem do .env
# Veja o arquivo .env.example para o formato esperado.
GOOGLE_SHEETS_ENABLED = True
GOOGLE_SHEETS_CREDENTIALS_PATH = os.path.join(
    BASE_DIR, "credentials", "google_service_account.json"
)
GOOGLE_SHEETS_SPREADSHEET_ID = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID")
GOOGLE_SHEETS_WORKSHEET_NAME = os.environ.get("GOOGLE_SHEETS_WORKSHEET_NAME", "Coleta")

# Screenshots de Produtos
SALVAR_PRINTS_ITENS = True
PRINTS_DIR = os.path.join(BASE_DIR, "screenshots")
