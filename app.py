import os
import numpy as np
import simplekml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict

app = FastAPI(title="Motor FTTH - Cascata e Unifilar")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TABELA_SPLITTERS = {"1x2": 2, "1x4": 4, "1x8": 8, "1x16": 16}
CORES_ANATEL = [
    "Verde", "Amarela", "Branca", "Azul", "Vermelha", "Violeta",
    "Marrom", "Rosa", "Preta", "Cinza", "Laranja", "Aqua"
]

class Coordenada(BaseModel):
    lat: float
    lng: float

class ElementoCascata(BaseModel):
    id: int
    lat: float
    lng: float
    pon_id: int
    pai_tipo: str  
    pai_id: int    

class RequestProjetoCascata(BaseModel):
    olt: Coordenada
    ceos: List[ElementoCascata]
    ctos: List[ElementoCascata]
    splitter_ceo: str
    splitter_cto: str
    potencia_olt: float

@app.get("/")
def read_root():
    return {"status": "Motor de Emendas Cascata Ativo"}

@app.post("/api/v1/calcular")
async def calcular_rede_cascata(dados: RequestProjetoCascata):
    if not dados.ceos:
        raise HTTPException(status_code=400, detail="Implante ao menos uma CEO no mapa.")
    if not dados.ctos:
        raise HTTPException(status_code=400, detail="Implante caixas CTO no mapa antes de processar.")

    limite_caixas = TABELA_SPLITTERS.get(dados.splitter_ceo, 8)
    for ceo in dados.ceos:
        qtd_ctos = len([c for c in dados.ctos if c.pon_id == ceo.pon_id])
        if qtd_ctos > limite_caixas:
            raise HTTPException(status_code=400, detail=f"A PON {ceo.pon_id} possui {qtd_ctos} CTOs. O limite para o splitter {dados.splitter_ceo} é de {limite_caixas} caixas!")

    try:
        kml = simplekml.Kml(name="Projeto Executivo - Rede Óptica")
        fol_backbone = kml.newfolder(name="01. BACKBONE (Cabo Alimentador)")
        fol_ceos = kml.newfolder(name="02. CAIXAS DE EMENDA (CEO)")
        fol_ctos_root = kml.newfolder(name="03. CAIXAS DE ATENDIMENTO (CTO)")
        fol_cabos_root = kml.newfolder(name="04. CABOS DE DISTRIBUIÇÃO")

        dict_ceos = {c.id: c for c in dados.ceos}
        dict_ctos = {c.id: c for c in dados.ctos}
        
        adjacencia_ctos: Dict[int, List[int]] = {c.id: [] for c in dados.ctos}
        filhos_diretos_ceo: Dict[int, List[int]] = {c.id: [] for c in dados.ceos}
        
        for cto in dados.ctos:
            if cto.pai_tipo == "CEO":
                if cto.pai_id in filhos_diretos_ceo:
                    filhos_diretos_ceo[cto.pai_id].append(cto.id)
            else:
                if cto.pai_id in adjacencia_ctos:
                    adjacencia_ctos[cto.pai_id].append(cto.id)

        dist_acumulada_nodos = {}
        fibra_atribuida_cto = {}
        tabela_emendas_master = {ceo.id: "" for ceo in dados.ceos}
        contador_fibra_global = {ceo.id: 1 for ceo in dados.ceos}
        
        def navegar_e_calcular(id_nodo: int, tipo_pai: str, pai_id_num: int, lat_pai: float, lng_pai: float, dist_base: float, ceo_origem_id: int):
            cto = dict_ctos[id_nodo]
            
            f_num = contador_fibra_global[ceo_origem_id]
            contador_fibra_global[ceo_origem_id] += 1
            fibra_atribuida_cto[cto.id] = f_num

            dist_lance = np.sqrt((cto.lat - lat_pai)**2 + (cto.lng - lng_pai)**2) * 111.32
            total_dist_rota = dist_base + dist_lance
            dist_acumulada_nodos[cto.id] = total_dist_rota

            def mapear_carga(nid):
                filhos = adjacencia_ctos.get(nid, [])
                sub_tot = len(filhos)
                for fid in filhos:
                    sub_tot += mapear_carga(fid)
                return sub_tot
            
            total_caixas_no_cabo = mapear_carga(cto.id) + 1
            tipo_cabo = "12FO (ASU-120)" if f_num > 6 or (f_num + total_caixas_no_cabo - 1) > 6 else "6FO (ASU-80)"

            cor_idx = (f_num - 1) % 12
            cor_fibra_anatel = CORES_ANATEL[cor_idx]

            potencia = dados.potencia_olt - ((total_dist_rota * 0.35) + 10.5 + 10.5 + 0.6)

            html_cto = f"""
            <div style="font-family:sans-serif; width:300px; color:#333;">
                <h3 style="background-color:#059669; color:white; padding:6px; margin:0; border-radius:4px 4px 0 0;">📦 UNIFILAR - CTO {cto.id:02d}</h3>
                <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                    <p><b>Porta Ativa:</b> PON {cto.pon_id:02d}</p>
                    <p><b>Origem Física do Lance:</b> {tipo_pai} {pai_id_num:02d}</p>
                    <p><b>Modelo do Cabo Utilizado:</b> {tipo_cabo}</p>
                    <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                    <p style="color:#2563eb; font-weight:bold;">✂️ Sangria Ativa: Fibra {f_num:02d} ({cor_fibra_anatel})</p>
                    <p style="color:#555;">Fibras anteriores já estão ocupadas. Fibras posteriores seguem passantes sem corte para as derivações subsequentes.</p>
                    <hr style="border:0; border-top:1px solid #eee; margin:6px 0;">
                    <p><b>Sinal no Atendimento:</b> <b>{potencia:.2f} dBm</b></p>
                </div>
            </div>
            """
            pnt_cto = fol_ctos_root.newpoint(name=f"PON {cto.pon_id:02d} - CTO {cto.id:02d}", coords=[(cto.lng, cto.lat)])
            pnt_cto.description = html_cto

            lin_c = fol_cabos_root.newlinestring(name=f"Cabo -> CTO {cto.id:02d}")
            lin_c.coords = [(lng_pai, lat_pai), (cto.lng, cto.lat)]
            lin_c.style.linestyle.width = 3
            lin_c.style.linestyle.color = "ff00ff00"

            tabela_emendas_master[ceo_origem_id] += f"""
            <tr>
                <td style='padding:5px; border:1px solid #ddd;'><b>Saída 0{f_num} (Splitter)</b></td>
                <td style='padding:5px; border:1px solid #ddd; color:#2563eb; font-weight:bold;'>Fibra {f_num:02d} ({cor_fibra_anatel})</td>
                <td style='padding:5px; border:1px solid #ddd;'>➡️ Alimenta a CTO {cto.id:02d} (Via {tipo_pai} {pai_id_num:02d})</td>
            </tr>
            """

            proximos_filhos = adjacencia_ctos.get(cto.id, [])
            proximos_filhos.sort(key=lambda fid: (dict_ctos[fid].lat - cto.lat)**2 + (dict_ctos[fid].lng - cto.lng)**2)
            
            for ff_id in proximos_filhos:
                navegar_e_calcular(ff_id, "CTO", cto.id, cto.lat, cto.lng, total_dist_rota, ceo_origem_id)

        for ceo in dados.ceos:
            dist_base_ceo = np.sqrt((ceo.lat - dados.olt.lat)**2 + (ceo.lng - dados.olt.lng)**2) * 111.32
            
            filhos_diretos = filhos_diretos_ceo.get(ceo.id, [])
            filhos_diretos.sort(key=lambda fid: (dict_ctos[fid].lat - ceo.lat)**2 + (dict_ctos[fid].lng - ceo.lng)**2)
            
            for cto_id_inicial in filhos_diretos:
                navegar_e_calcular(cto_id_inicial, "CEO", ceo.id, ceo.lat, ceo.lng, dist_base_ceo, ceo.id)

            html_master_ceo = f"""
            <div style="font-family:sans-serif; width:420px; color:#333;">
                <h3 style="background-color:#1e3a8a; color:white; padding:8px; margin:0; border-radius:4px 4px 0 0; font-size:14px;">📋 RELATÓRIO DE EMENDA - CEO {ceo.id:02d}</h3>
                <div style="padding:10px; border:1px solid #ddd; background:#fff; font-size:12px;">
                    <p><b>Porta OLT Alimentadora:</b> PON {ceo.pon_id:02d}</p>
                    <p><b>Splitter de 1º Nível Interno:</b> {dados.splitter_ceo}</p>
                    <p style="color:#16a34a; font-weight:bold;">🟢 Entrada Primária: Fibra 01 (Verde) do Cabo Tronco ➡️ IN do Splitter</p>
                    <hr style="margin:8px 0; border:0; border-top:1px solid #eee;">
                    <h4 style="margin:0 0 5px 0; color:#1e40af;">Mapeamento do Splitter para os Cabos de Distribuição (ASU):</h4>
                    <table style="width:100%; border-collapse:collapse; font-size:11px; text-align:left;" border="1" cellpadding="4" cellspacing="0">
                        <tr style="background:#f3f4f6; font-weight:bold;">
                            <th style='padding:5px; border:1px solid #ddd;'>Saída Splitter</th>
                            <th style='padding:5px; border:1px solid #ddd;'>Fusão no Cabo (Fibra/Cor)</th>
                            <th style='padding:5px; border:1px solid #ddd;'>Destino Final Atendido</th>
                        </tr>
                        {tabela_emendas_master[ceo.id]}
                    </table>
                </div>
            </div>
            """
            pnt_ceo = fol_ceos.newpoint(name=f"CEO {ceo.id:02d}", coords=[(ceo.lng, ceo.lat)])
            pnt_ceo.description = html_master_ceo

            lin_t = fol_backbone.newlinestring(name=f"Cabo Tronco -> CEO {ceo.id:02d}")
            lin_t.coords = [(dados.olt.lng, dados.olt.lat), (ceo.lng, ceo.lat)]
            lin_t.style.linestyle.width = 5
            lin_t.style.linestyle.color = "ff0000ff"

        ctos_resposta = []
        for cto in dados.ctos:
            f_num_real = fibra_atribuida_cto.get(cto.id, 1)
            cor_idx = (f_num_real - 1) % 12
            dist_total_m = dist_acumulada_nodos.get(cto.id, 0)
            potencia_calc = dados.potencia_olt - ((dist_total_m * 0.35) + 10.5 + 10.5 + 0.6)
            
            ctos_resposta.append({
                "id": cto.id, "lat": cto.lat, "lng": cto.lng, "pon_id": cto.pon_id, 
                "pai_tipo": cto.pai_tipo, "pai_id": cto.pai_id,
                "potencia_dbm": round(potencia_calc, 2),
                "cabo_utilizado": "12FO (ASU-120)" if f_num_real > 6 else "6FO (ASU-80)",
                "fibra_sangrada": f"Fibra {f_num_real:02d} ({CORES_ANATEL[cor_idx]})"
            })

        return {
            "status": "sucesso",
            "ceos": [{"id": c.id, "lat": c.lat, "lng": c.lng, "pon_id": c.pon_id} for c in dados.ceos],
            "ctos": ctos_resposta,
            "kml_conteudo": kml.kml()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro interno no motor unifilar estrito: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
