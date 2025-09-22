# analisador.py (Versão 9.4 - Leitor Hiki Supremo)
import os
import fitz
import re
import json

PASTA_DATASHEETS = "datasheets"
ARQUIVO_SAIDA = "analise_de_produtos.json"

# =========================
# Utilidades
# =========================
def extrair_texto_do_pdf(pdf_path):
    try:
        with fitz.open(pdf_path) as doc:
            return "".join(page.get_text() for page in doc)
    except Exception as e:
        print(f"[ERRO] Não foi possível ler {pdf_path}: {e}")
        return None

def clean_value(text):
    if not text:
        return ""
    text = re.sub(r'[»¹²³⁴⁵⁶⁷⁸⁹®™©]', '', text)
    text = text.replace("", " ").replace("•", " ")
    lixo = [
        "intelbras.com", "www.hikvision.com", "avigilon.com",
        "Material do case", "Inteligência Artificial", "L × A × P",
        "As VIPs Intelbras", "Informações sujeitas a alterações"
    ]
    for l in lixo:
        text = text.split(l)[0]
    return re.sub(r'\s+', ' ', text).strip(" :–;,.()")

def limitar_valor(valor, limite=100):
    if not valor:
        return ""
    return valor[:limite].strip()

# =========================
# Funções de busca
# =========================
def buscar_valor(texto, padrao):
    valor_encontrado = ""
    match = re.search(rf"{padrao}\s*[:\-]?\s*([^\n]{{3,}})", texto, re.IGNORECASE)
    if match:
        candidato = clean_value(match.group(1))
        if not re.search(padrao, candidato, re.IGNORECASE):
            valor_encontrado = candidato
    if not valor_encontrado:
        match = re.search(rf"{padrao}(?:\s*\n)+\s*([^\n]+)", texto, re.IGNORECASE)
        if match:
            candidato = clean_value(match.group(1))
            if not re.search(padrao, candidato, re.IGNORECASE):
                valor_encontrado = candidato
    return valor_encontrado

# =========================
# Normalizadores
# =========================
def normalizar_resolucao(valor):
    if not valor:
        return "Não encontrado"
    match = re.search(r"(\d{3,4})\s*[xX×]\s*(\d{3,4})", valor)
    if match:
        w, h = map(int, match.groups())
        mp = round((w * h) / 1_000_000, 1)
        return f"{mp} MP ({w}x{h})"
    return clean_value(valor)

def normalizar_peso(valor):
    if not valor:
        return "Não encontrado"
    num_search = re.search(r"(\d[\d,.]*)", valor)
    if not num_search:
        return "Não encontrado"
    num_str = num_search.group(1).replace(",", ".")
    try:
        parts = num_str.split('.')
        if len(parts) > 2:
            num_str = "".join(parts[:-1]) + "." + parts[-1]
        num = float(num_str)
    except ValueError:
        return "Não encontrado"
    if "kg" in valor.lower():
        return f"{int(num * 1000)} g"
    if "lb" in valor.lower():
        return f"{int(num * 453.6)} g"
    if "g" in valor.lower():
        return f"{int(num)} g"
    return "Não encontrado"

def normalizar_lente(valor):
    if not valor:
        return "Não encontrado"
    v = valor.replace(",", ".").lower().strip()
    m_range = re.search(r"(\d+\.?\d*)\s*mm\s*(?:to|-|~|até)\s*(\d+\.?\d*)\s*mm", v)
    if m_range:
        return f"{m_range.group(1)} mm - {m_range.group(2)} mm (Varifocal)"
    m_fixed = re.search(r"(\d+\.?\d*)\s*mm", v)
    if m_fixed:
        return f"{m_fixed.group(1)} mm (Fixa)"
    return valor

def normalizar_temperatura(valor):
    if not valor:
        return {"min": None, "max": None, "unidade": "°C"}
    nums = re.findall(r"-?\d{1,3}", valor)
    if len(nums) >= 2:
        return {"min": int(nums[0]), "max": int(nums[1]), "unidade": "°C"}
    elif len(nums) == 1:
        return {"min": int(nums[0]), "max": None, "unidade": "°C"}
    return {"min": None, "max": None, "unidade": "°C"}

def normalizar_protocolos(valor):
    if not valor:
        return []
    candidatos = re.split(r"[;,/]", valor)
    return [clean_value(v) for v in candidatos if v.strip()]

def normalizar_navegadores(valor):
    if not valor:
        return []
    candidatos = re.split(r"[;,/]", valor)
    return [v.strip() for v in candidatos if v.strip()]

def normalizar_compressao_video(valor):
    if not valor:
        return "Não encontrado"
    return ", ".join([v.strip() for v in re.split(r"[;,/]", valor) if v.strip()])

def normalizar_distancia_ir(valor):
    if not valor:
        return "Não encontrado"
    match = re.search(r"(\d+)\s*m", valor)
    return f"{match.group(1)} m" if match else "Não encontrado"

# =========================
# Tags por padrão no nome do modelo
# =========================
TAGS_POR_SIGLA = {
    "LPR": "Leitura de Placas",
    "SD": "Speed Dome",
    "SC": "Super Color",
    "FC": "Full Color / Super Color",
    "FC+": "Full Color+",
    "IA": "Inteligência Artificial",
    "D": "Dome",
    "B": "Bullet",
    "PAN": "Panorâmica",
    "PTZ": "Motorizada",
    "STARVIS": "Sensor STARVIS"
}

def extrair_tags_por_nome(modelo, texto):
    tags = []
    for sigla, significado in TAGS_POR_SIGLA.items():
        if re.search(rf"(?:\b|[-_+]){sigla}(?:\b|[-_+])", modelo, re.IGNORECASE):
            tags.append(significado)
    extras = {
        "PoE": "PoE",
        "SMD": "Smart Motion Detection",
        "Face Detection": "Detecção Facial",
        "People Counting": "Contagem de Pessoas",
    }
    for termo, significado in extras.items():
        if termo.lower() in texto.lower():
            tags.append(significado)
    return sorted(set(tags))

# =========================
# Padrões por categoria
# =========================
PATTERNS = {
    "video": {
        "sensor_imagem": r"(?:Sensor de imagem|Image Sensor|Image Device)",
        "wdr": r"(?:WDR|Wide Dynamic Range|DWDR|120 dB WDR)",
        "compressao_video": r"(?:Compressão de vídeo|Video Compression)",
        "taxa_de_bits": r"(?:Taxa de bits|Video Bit Rate|Bitrate|Data rate|Stream Rate)",
    },
    "audio": {
        "microfone_embutido": r"(?:Microfone embutido|Built-in Microphone)",
        "compressao_audio": r"(?:Compressão de áudio|Audio Compression)",
    },
    "rede": {
        "interface_rede": r"(?:Interface de rede|Ethernet Interface|Network Interface|\bLAN\b)",
        "throughput": r"(?:Throughput Máximo|Max\. Throughput|Throughput)",
        "protocolos": r"(?:Protocolos e serviços suportados|Protocols|Supported Protocols)",
        "onvif": r"\b(Onvif|Open Network Video Interface)\b",
        "navegador": r"(?:Navegador|Web Browser|Browser)",
    },
    "inteligencia": {
        "deteccao_movimento": r"(?:Detecção de movimento|Motion detection|Basic Event)",
        "regiao_interesse": r"(?:Região de interesse|Region of Interest|\bROI\b)",
        "protecao_perimetral": r"(?:Proteção Perimetral|Perimeter Protection|Intrusion|Line crossing)",
    },
    "energia": {
        "tensao_alimentacao": r"(?:Alimentação|Power Supply|Power Source)",
        "consumo_potencia": r"(?:Consumo|Power Consumption\b)",
    },
    "fisico": {
        "peso": r"\b(Peso|Weight)\b",
        "temperatura_operacao": r"(?:Temperatura de operação|Operating Conditions|Environment)",
    }
}

# =========================
# Padrões Hikvision (em inglês)
# =========================
PATTERNS_HIKVISION = {
    "video": {
        "compressao_video": r"(?:H\.265\+|H\.265|H\.264\+|H\.264|MJPEG)",
        "resolucao": r"(\d{3,4}\s*[xX×]\s*\d{3,4})",
        "fps": r"(\d+\s*fps)"
    },
    "rede": {
        "interface_rede": r"(?:RJ-45|Ethernet|Network Interface|PoE)",
        "throughput": r"(?:Max\. Throughput|Mbps)",
        "protocolos": r"(?:TCP/IP|UDP|HTTP|HTTPS|DHCP|DNS|NTP|ONVIF|RTSP|RTP)",
        "onvif": r"\b(Onvif|Open Network Video Interface)\b",
        "navegador": r"(?:Web Browser|IE|Chrome|Firefox)"
    },
    "inteligencia": {
        "line_crossing": r"(?:Line Crossing Detection)",
        "intrusion": r"(?:Intrusion Detection)",
        "people_counting": r"(?:People Counting)",
        "face_detection": r"(?:Face Detection)"
    },
    "energia": {
        "alimentacao": r"(?:12 VDC|PoE|PoE\+)"
    },
    "fisico": {
        "grau_protecao": r"(?:IP\d{2})",
        "dimensoes": r"(\d[\d\.]+\s*mm\s*[xX×]\s*\d[\d\.]+\s*mm\s*[xX×]\s*\d[\d\.]+\s*mm)"
    }
}

# =========================
# Analisador principal
# =========================
def analisar_datasheet(texto_original):
    especificacoes = {"video": {}, "audio": {}, "rede": {}, "inteligencia": {}, "energia": {}, "fisico": {}}

    # Fabricante
    if "intelbras" in texto_original.lower():
        especificacoes["fabricante"] = "Intelbras"
    elif "hikvision" in texto_original.lower():
        especificacoes["fabricante"] = "Hikvision"
    elif "avigilon" in texto_original.lower():
        especificacoes["fabricante"] = "Avigilon"
    else:
        especificacoes["fabricante"] = "Desconhecido"

    # Modelo
    stop_words = r"(?:Sensor|Pixels|Lente|Especificações|Câmera|Distância|Compressão|Resolução)"
    intelbras_pattern = rf"\b(VIP(?:\s|[C|M|W])*?\d{{3,5}}(?:[\s\-]+[A-Z\d\+\.\/]+(?!\s*{stop_words}))*)\b"
    hikvision_pattern = r"\b(DS-2CD[\w\d\-]+)\b"
    avigilon_pattern = r"\b(H4A-[\w\-]+)\b"
    modelos = re.findall(f"({intelbras_pattern}|{hikvision_pattern}|{avigilon_pattern})", texto_original, re.IGNORECASE)
    modelo_produto = ", ".join(sorted(set([m[0].strip() for m in modelos]))) or "Não encontrado"
    especificacoes["modelo_produto"] = clean_value(modelo_produto)
    especificacoes["tags"] = extrair_tags_por_nome(modelo_produto, texto_original)

    # Distância focal
    lente_m = re.search(r"(\d+\.?\d*\s*(?:mm)?\s*(?:to|-)\s*\d+\.?\d*\s*mm|\b\d\.?\d?\s*mm\b)", texto_original, re.IGNORECASE)
    especificacoes["distancia_focal"] = normalizar_lente(lente_m.group(1) if lente_m else "")

    # Resolução
    resolucao_m = re.search(r"(\d{3,4}\s*[xX×]\s*\d{3,4})", texto_original)
    especificacoes["video"]["resolucao_maxima"] = normalizar_resolucao(resolucao_m.group(1) if resolucao_m else None)
    especificacoes["video"]["pixels_efetivos"] = especificacoes["video"]["resolucao_maxima"]

    # Grau de proteção
    ip_match = re.search(r"(IP\d{2})", texto_original, re.IGNORECASE)
    especificacoes["fisico"]["grau_protecao"] = ip_match.group(1).upper() if ip_match else "Não encontrado"

    # Dimensões
    dimensoes_m = re.search(r"(\d[\d\.]+\s*mm\s*[xX×]\s*\d[\d\.]+\s*mm\s*[xX×]\s*\d[\d\.]+\s*mm)", texto_original)
    especificacoes["fisico"]["dimensoes"] = clean_value(dimensoes_m.group(1)) if dimensoes_m else "Não encontrado"

    # Campos via padrões
    if especificacoes["fabricante"] == "Hikvision":
        for categoria, campos in PATTERNS_HIKVISION.items():
            for chave, padrao in campos.items():
                valor = buscar_valor(texto_original, padrao)
                # Normalizações específicas
                if chave == "compressao_video":
                    valor = normalizar_compressao_video(valor)
                elif chave in ["line_crossing", "intrusion", "people_counting", "face_detection"]:
                    valor = "Sim" if valor else "Não"
                elif chave == "alimentacao":
                    valor = clean_value(valor)
                elif chave == "dimensoes":
                    valor = clean_value(valor)
                elif chave == "grau_protecao":
                    valor = clean_value(valor)
                elif chave == "protocolos":
                    valor = normalizar_protocolos(valor)
                elif chave == "navegador":
                    valor = normalizar_navegadores(valor)
                else:
                    valor = clean_value(valor)
                especificacoes[categoria][chave] = valor if valor else "Não encontrado"
    else:
        for categoria, campos in PATTERNS.items():
            for chave, padrao in campos.items():
                valor = buscar_valor(texto_original, padrao)
                if chave == "peso":
                    valor = normalizar_peso(valor)
                elif chave == "temperatura_operacao":
                    valor = normalizar_temperatura(valor)
                elif chave == "protocolos":
                    valor = normalizar_protocolos(valor)
                elif chave == "navegador":
                    valor = normalizar_navegadores(valor)
                else:
                    valor = clean_value(valor)
                especificacoes[categoria][chave] = valor if valor else "Não encontrado"

    return especificacoes

# =========================
# Execução principal
# =========================
def main():
    print("--- Iniciando Análise de Datasheets (Versão 9.4 - Leitor Hiki Supremo) ---")
    if not os.path.exists(PASTA_DATASHEETS):
        print(f"Pasta '{PASTA_DATASHEETS}' não encontrada.")
        os.makedirs(PASTA_DATASHEETS)
        return
    todos_os_dados = {}
    arquivos_pdf = [f for f in os.listdir(PASTA_DATASHEETS) if f.lower().endswith(".pdf")]
    if not arquivos_pdf:
        print(f"Nenhum PDF encontrado em '{PASTA_DATASHEETS}'.")
        return
    print(f"Encontrados {len(arquivos_pdf)} PDF(s). Iniciando análise...")
    for i, filename in enumerate(arquivos_pdf, start=1):
        print(f"[{i}/{len(arquivos_pdf)}] Lendo '{filename}'...")
        texto = extrair_texto_do_pdf(os.path.join(PASTA_DATASHEETS, filename))
        if texto:
            todos_os_dados[filename] = analisar_datasheet(texto)
            print(f"  [OK] {filename} analisado.")
        else:
            print(f"  [AVISO] Não foi possível extrair texto de {filename}.")
    try:
        with open(ARQUIVO_SAIDA, "w", encoding="utf-8") as f:
            json.dump(todos_os_dados, f, indent=4, ensure_ascii=False)
        print(f"\n--- Finalizado! Resultados salvos em '{ARQUIVO_SAIDA}' ---")
    except Exception as e:
        print(f"[ERRO] Falha ao salvar JSON: {e}")

if __name__ == "__main__":
    main()
