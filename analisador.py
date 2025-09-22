# analisador.py (Versão Definitiva)
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
        "As VIPs Intelbras", "Informações sujeitas a alterações",
        "Incorpora produto homologado pela Anatel sob os",
        "fornece imagem de"
    ]
    for l in lixo:
        text = text.split(l)[0]
    return re.sub(r'\s+', ' ', text).strip(" :–;,.()")

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
    # >>> CORREÇÃO FINAL <<< Regex mais robusto para aceitar quebras de linha
    match = re.search(r"(\d{3,4})\s*[xX×\n\s]*\s*(\d{3,4})", valor)
    if match:
        w, h = map(int, match.groups())
        mp = round((w * h) / 1_000_000, 1)
        return f"{mp} MP ({w}x{h})"
    return clean_value(valor)

def normalizar_peso(valor):
    if not valor: return "Não encontrado"
    num_search = re.search(r"(\d[\d,.]*)", valor)
    if not num_search: return "Não encontrado"
    num_str = num_search.group(1).replace(",", ".")
    try:
        parts = num_str.split('.')
        if len(parts) > 2: num_str = "".join(parts[:-1]) + "." + parts[-1]
        num = float(num_str)
        if "kg" in valor.lower(): return f"{int(num * 1000)} g"
        if "lb" in valor.lower(): return f"{int(num * 453.6)} g"
        if "g" in valor.lower(): return f"{int(num)} g"
    except ValueError: return "Não encontrado"
    return "Não encontrado"

def normalizar_lente(valor):
    if not valor: return "Não encontrado"
    v = valor.replace(",", ".").lower().strip()
    m_range = re.search(r"(\d+\.?\d*)\s*(?:mm)?\s*(?:to|-|~|até)\s*(\d+\.?\d*)\s*mm", v)
    if m_range: return f"{m_range.group(1)} mm - {m_range.group(2)} mm (Varifocal)"
    m_fixed = re.search(r"(\d+\.?\d*)\s*mm", v)
    if m_fixed: return f"{m_fixed.group(1)} mm (Fixa)"
    return valor

def normalizar_temperatura(valor):
    if not valor: return {"min": None, "max": None, "unidade": "°C"}
    temp_part = valor.split('/')[0]
    nums = [int(n) for n in re.findall(r'-?\d+', temp_part)]
    if not nums: return {"min": None, "max": None, "unidade": "°C"}
    min_temp, max_temp = (min(nums), max(nums)) if len(nums) > 1 else (nums[0], nums[0])
    if '°F' in valor or 'Fahrenheit' in valor:
        min_temp = int((min_temp - 32) * 5/9)
        max_temp = int((max_temp - 32) * 5/9)
    return {"min": min_temp, "max": max_temp, "unidade": "°C"}

def normalizar_protocolos(valor):
    if not valor: return []
    candidatos = re.split(r'[;,/]', valor)
    return sorted(set([clean_value(v) for v in candidatos if v.strip() and len(v) > 2]))

def normalizar_navegadores(valor):
    if not valor: return []
    candidatos = re.split(r"[,;/]", valor)
    return [v.strip() for v in candidatos if v.strip()]

# =========================
# Tags
# =========================
TAGS_POR_SIGLA = {
    "LPR": "Leitura de Placas","SD": "Speed Dome","SC": "Super Color","FC": "Full Color / Super Color","FC+": "Full Color+","IA": "Inteligência Artificial","D": "Dome","B": "Bullet","PAN": "Panorâmica","PTZ": "Motorizada","STARVIS": "Sensor STARVIS"
}

def extrair_tags_por_nome(modelo, texto):
    tags = []
    for sigla, significado in TAGS_POR_SIGLA.items():
        if re.search(rf"(?:\b|[-_+]){sigla}(?:\b|[-_+])", modelo, re.IGNORECASE):
            tags.append(significado)
    extras = {"PoE": "PoE", "SMD": "Smart Motion Detection", "Face Detection": "Detecção Facial", "People Counting": "Contagem de Pessoas"}
    for termo, significado in extras.items():
        if termo.lower() in texto.lower():
            tags.append(significado)
    return sorted(set(tags))

# =========================
# Padrões
# =========================
PATTERNS = {
    "video": {"sensor_imagem": r"(?:Sensor de imagem|Image Sensor|Image Device)","wdr": r"(?:WDR|Wide Dynamic Range|DWDR|120 dB WDR)","compressao_video": r"(?:Compressão de vídeo|Video Compression)","taxa_de_bits": r"(?:Taxa de bits|Video Bit Rate|Bitrate|Data rate|Stream Rate)",},"audio": {"microfone_embutido": r"(?:Microfone embutido|Built-in Microphone)","compressao_audio": r"(?:Compressão de áudio|Audio Compression)",},"rede": {"interface_rede": r"(?:Interface de rede|Ethernet Interface|Network Interface|\bLAN\b)","throughput": r"(?:Throughput Máximo|Max\. Throughput|Throughput)","protocolos": r"(?:Protocolos e serviços suportados|Protocols|Supported Protocols)","onvif": r"\b(Onvif|Open Network Video Interface)\b","navegador": r"(?:Navegador|Web Browser|Browser)",},"inteligencia": {"deteccao_movimento": r"(?:Detecção de movimento|Motion detection|Basic Event)","regiao_interesse": r"(?:Região de interesse|Region of Interest|\bROI\b)","protecao_perimetral": r"(?:Proteção Perimetral|Perimeter Protection|Intrusion|Line crossing)",},"energia": {"tensao_alimentacao": r"(?:Alimentação|Power Supply|Power Source)","consumo_potencia": r"(?:Consumo|Power Consumption and Current|\bPower Consumption\b)",},"fisico": {"peso": r"\b(Peso|Weight)\b","temperatura_operacao": r"(?:Temperatura de operação|Operating Conditions|Environment)",}
}

PATTERNS_HIKVISION_CORRIGIDO = {
    "video": {"sensor_imagem": r"Image Sensor","wdr": r"Wide Dynamic Range \(WDR\)","compressao_video": r"Video Compression","taxa_de_bits": r"Video Bit Rate"},
    "audio": {"microfone_embutido": r"Built-in Microphone","compressao_audio": r"Audio Compression"},
    "rede": {"interface_rede": r"Ethernet Interface","protocolos": r"Protocols","navegador": r"Web Browser"},
    "energia": {"tensao_alimentacao": r"Power Supply","consumo_potencia": r"Power Consumption and Current"},
    "fisico": {"peso": r"^Weight","temperatura_operacao": r"Operating Conditions|Storage Conditions","distancia_ir": r"IR Range|Supplement Light Range"}
}

def analisar_apenas_hikvision(texto, especificacoes):
    for categoria, campos in PATTERNS_HIKVISION_CORRIGIDO.items():
        for chave, padrao in campos.items():
            valor = buscar_valor(texto, padrao)
            especificacoes[categoria][chave] = valor if valor else "Não encontrado"
    
    especificacoes["inteligencia"]["deteccao_movimento"] = buscar_valor(texto, r"Basic Event")
    especificacoes["inteligencia"]["protecao_perimetral"] = buscar_valor(texto, r"Perimeter Protection")
    especificacoes["inteligencia"]["regiao_interesse"] = buscar_valor(texto, r"Region of Interest \(ROI\)")

    especificacoes["fisico"]["temperatura_operacao"] = normalizar_temperatura(especificacoes["fisico"]["temperatura_operacao"])
    especificacoes["fisico"]["peso"] = normalizar_peso(especificacoes["fisico"]["peso"])
    especificacoes["rede"]["protocolos"] = normalizar_protocolos(especificacoes["rede"].get("protocolos", ""))
    especificacoes["rede"]["navegador"] = normalizar_navegadores(especificacoes["rede"].get("navegador", ""))
    
    return especificacoes

# =========================
# Analisador principal
# =========================
def analisar_datasheet(texto_original):
    especificacoes = {"video": {}, "audio": {}, "rede": {}, "inteligencia": {}, "energia": {}, "fisico": {}}
    
    if "intelbras" in texto_original.lower(): especificacoes["fabricante"] = "Intelbras"
    elif "hikvision" in texto_original.lower(): especificacoes["fabricante"] = "Hikvision"
    elif "avigilon" in texto_original.lower(): especificacoes["fabricante"] = "Avigilon"
    else: especificacoes["fabricante"] = "Desconhecido"

    stop_words = r"(?:Sensor|Pixels|Lente|Especificações|Câmera|Distância|Compressão|Resolução)"
    # >>> CORREÇÃO FINAL <<< Regex menos "guloso" para evitar capturar lixo
    intelbras_pattern = rf"\b(VIP(?:\s|[C|M|W])*?\d{{3,5}}(?:[\s\-]+[A-Z\d\+\.\/]+(?!\s*{stop_words})){{0,4}})\b"
    hikvision_pattern = r"\b(DS-2[CD|DE][\w\d\-]+)\b"
    avigilon_pattern = r"\b(H4A-[\w\-]+)\b"
    modelos = re.findall(f"({intelbras_pattern}|{hikvision_pattern}|{avigilon_pattern})", texto_original, re.IGNORECASE)
    modelo_produto = ", ".join(sorted(set([m[0].strip() for m in modelos if m[0]]))) or "Não encontrado"
    especificacoes["modelo_produto"] = clean_value(modelo_produto)
    especificacoes["tags"] = extrair_tags_por_nome(modelo_produto, texto_original)

    lente_m = re.search(r"(\d+\.?\d*\s*(?:mm)?\s*(?:to|-)\s*\d+\.?\d*\s*mm|\b\d+\.?\d*\s*mm\b)", texto_original, re.IGNORECASE)
    especificacoes["distancia_focal"] = normalizar_lente(lente_m.group(1) if lente_m else "")
    
    # Busca pela resolução no texto todo primeiro
    resolucao_m = re.search(r"(\d{3,4}\s*[xX×\n\s]*\s*\d{3,4})", texto_original)
    especificacoes["video"]["resolucao_maxima"] = normalizar_resolucao(resolucao_m.group(0) if resolucao_m else None)
    especificacoes["video"]["pixels_efetivos"] = especificacoes["video"]["resolucao_maxima"]
    
    ip_match = re.search(r"(IP\d{2})", texto_original, re.IGNORECASE)
    especificacoes["fisico"]["grau_protecao"] = ip_match.group(1).upper() if ip_match else "Não encontrado"
    dimensoes_m = re.search(r"(\d[\d\.]+\s*mm\s*[xX×]\s*\d[\d\.]+\s*mm\s*[xX×]\s*\d[\d\.]+\s*mm)", texto_original)
    especificacoes["fisico"]["dimensoes"] = clean_value(dimensoes_m.group(1) if dimensoes_m else "Não encontrado")

    if especificacoes["fabricante"] == "Hikvision":
        especificacoes = analisar_apenas_hikvision(texto_original, especificacoes)
    else:
        for categoria, campos in PATTERNS.items():
            for chave, padrao in campos.items():
                valor = buscar_valor(texto_original, padrao)
                if chave == "peso": valor = normalizar_peso(valor)
                elif chave == "temperatura_operacao": valor = normalizar_temperatura(valor)
                elif chave == "protocolos": valor = normalizar_protocolos(valor)
                elif chave == "navegador": valor = normalizar_navegadores(valor)
                else: valor = clean_value(valor)
                especificacoes[categoria][chave] = valor if valor else "Não encontrado"
    return especificacoes

# =========================
# Execução principal
# =========================
def main():
    print(f"--- Iniciando Análise de Datasheets (Versão 10.0 - Final) ---")
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