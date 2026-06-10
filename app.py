from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List
import simplekml
import numpy as np

app = FastAPI(title="Motor FTTH Cascata")

# Habilita CORS para sua Vercel
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

@app.post("/api/v1/calcular")
async def calcular(dados: RequestProjeto):
    try:
        kml = simplekml.Kml(name="Projeto_FTTH")
        
        # Processamento simples para garantir retorno compatível com seu JS
        # O log no JS espera os campos: id, pai_tipo, pai_id, cabo_utilizado, fibra_sangrada, potencia_dbm
        
        resp_ctos = []
        for cto in dados.ctos:
            # Simulação de cálculo de sinal
            potencia_dbm = dados.potencia_olt - 20.5 # Exemplo simples
            
            resp_ctos.append({
                "id": cto.id,
                "pai_tipo": cto.pai_tipo,
                "pai_id": cto.pai_id,
                "cabo_utilizado": "ASU-6FO",
                "fibra_sangrada": "Fibra 1 (Verde)",
                "potencia_dbm": round(potencia_dbm, 2)
            })

        return {
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng} for c in dados.ceos],
            "ctos": resp_ctos,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
