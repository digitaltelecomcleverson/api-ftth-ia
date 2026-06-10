from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import simplekml
import numpy as np

app = FastAPI()

# Configuração de CORS para o seu frontend na Vercel
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/")
def read_root():
    return {"status": "API Digital Telecom Online"}

@app.post("/api/v1/calcular")
async def calcular(dados: RequestProjeto):
    # Lógica de processamento básica
    return {
        "status": "sucesso",
        "ceos": [{"id": c.id} for c in dados.ceos],
        "ctos": [{"id": c.id, "potencia_dbm": -20.5} for c in dados.ctos],
        "kml_conteudo": "<?xml version='1.0' encoding='UTF-8'?><kml></kml>"
    }
