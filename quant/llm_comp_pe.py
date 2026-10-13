"""LLM辅助可比公司PE计算

用大模型根据公司行业/主营/产品推荐3-5只可比上市公司,
再从东财实时获取PE_TTM, 取中位数作为可比PE。
失败时回退到行业PE基准。
"""
import os, sys, json, logging, requests
from pathlib import Path

logger = logging.getLogger("llm_comp_pe")

BASE_DIR = Path(__file__).parent.parent

# LLM API 配置 (火山引擎 ARK)
ARK_API_KEY = None
ARK_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
ARK_MODEL = "doubao-pro-32k"  # 可改为 endpoint ID (ep-xxx)

def _load_api_key():
    global ARK_API_KEY
    if ARK_API_KEY:
        return ARK_API_KEY
    key_file = BASE_DIR / '.api_key'
    if key_file.exists():
        ARK_API_KEY = key_file.read_text().strip()
    return ARK_API_KEY


def _call_llm(prompt, max_tokens=500):
    """调用火山引擎ARK API"""
    api_key = _load_api_key()
    if not api_key:
        logger.warning("未找到LLM API key")
        return None
    try:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        }
        payload = {
            'model': ARK_MODEL,
            'messages': [
                {'role': 'system', 'content': '你是A股行业研究专家, 擅长找可比公司。只输出JSON, 不要解释。'},
                {'role': 'user', 'content': prompt},
            ],
            'max_tokens': max_tokens,
            'temperature': 0.3,
        }
        r = requests.post(ARK_ENDPOINT, headers=headers, json=payload, timeout=20)
        d = r.json()
        content = d['choices'][0]['message']['content']
        # 提取JSON
        start = content.find('{')
        end = content.rfind('}') + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
        return None
    except Exception as e:
        logger.warning("LLM调用失败: %s" % e)
        return None


def recommend_comparable_companies(name, industry, business_scope, main_products=""):
    """用LLM推荐可比公司

    Returns: list of {name, code, reason}
    """
    prompt = f"""请为以下A股上市公司推荐3-5只最可比的A股上市公司(同行业、同业务模式、同产品类型):

公司名称: {name}
所属行业: {industry}
主营业务: {business_scope[:300]}
主要产品: {main_products[:200]}

要求:
1. 必须是A股已上市公司(沪/深/北交所)
2. 业务相似度高, 不是泛行业公司
3. 优先选择市值和规模相近的公司

只输出JSON格式:
{{"comparables": [{{"name": "公司名", "code": "6位股票代码", "reason": "可比原因"}}]}}
"""
    result = _call_llm(prompt, max_tokens=800)
    if result and 'comparables' in result:
        return result['comparables']
    return []


def fetch_pe_ttm(code):
    """获取单只股票的PE_TTM (东财实时行情)"""
    secid = f"1.{code}" if code.startswith('6') else f"0.{code}"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f57,f58,f162,f163,f164,f167"
    try:
        r = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        d = r.json()
        data = d.get('data', {})
        pe_ttm = data.get('f162')  # PE(TTM)
        if pe_ttm and pe_ttm > 0:
            return pe_ttm
    except Exception as e:
        logger.debug("获取PE失败 %s: %s" % (code, e))
    return None


def compute_comparable_pe(name, industry, business_scope, main_products="", fallback_pe=25):
    """计算可比公司PE (LLM推荐 + 实时PE_TTM中位数)

    Returns: (pe_median, comparables_info)
    """
    comparables = recommend_comparable_companies(name, industry, business_scope, main_products)
    if not comparables:
        logger.info("LLM未推荐可比公司, 使用回退PE=%.1f" % fallback_pe)
        return fallback_pe, []

    pe_list = []
    info = []
    for c in comparables:
        code = c.get('code', '')
        cname = c.get('name', '')
        reason = c.get('reason', '')
        pe = fetch_pe_ttm(code)
        info.append({'name': cname, 'code': code, 'pe_ttm': pe, 'reason': reason})
        if pe and 0 < pe < 200:  # 排除异常值
            pe_list.append(pe)

    if pe_list:
        pe_list.sort()
        median = pe_list[len(pe_list) // 2]
        logger.info("可比公司PE中位数=%.1f (公司: %s)" % (median, ', '.join(f"{c['name']}({c['pe_ttm']})" for c in info if c['pe_ttm'])))
        return round(median, 1), info

    logger.info("可比公司PE全部无效, 使用回退PE=%.1f" % fallback_pe)
    return fallback_pe, info


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    # 测试
    pe, info = compute_comparable_pe(
        "格林生物", "基础化工-化学制品",
        "香精香料的研发、生产和销售, 产品包括日化香精、食用香精等",
        "日化香精、食用香精"
    )
    print("可比PE:", pe)
    print("可比公司:", json.dumps(info, ensure_ascii=False, indent=2))
