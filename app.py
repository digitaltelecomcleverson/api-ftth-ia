from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List

app = FastAPI()

# Configuração de CORS para aceitar conexões da sua Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rota principal para o Render saber que a API está "Live"
@app.get("/")
def read_root():
    return {"status": "API Digital Telecom Online"}

# Definição do modelo de dados
class Coordenada(BaseModel):
    lat: float
    lng: float

class Elemento(BaseModel):
    id: int
    lat: float
    lng: float
    pon_id: int
    pai_tipo: str
    pai_id: int

class RequestProjeto(BaseModel):
    olt: Coordenada
    ceos: List[Elemento]
    ctos: List[Elemento]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

# Rota corrigida conforme o seu frontend chama
@app.post("/api/v1/calcular")
async def calcular(dados: RequestProjeto):
    return {"status": "processado", "kml_conteudo": "<kml>...</kml>"}
