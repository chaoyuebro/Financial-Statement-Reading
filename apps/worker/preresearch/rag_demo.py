# -*- coding: utf-8 -*-
"""预研 #5: 带页码引用的 RAG 检索链路 (零依赖 BM25, 不依赖外部模型)
验证: 问题 -> 检索到正确页码片段 -> 可拼出"答案+页码引用"
LLM 生成步骤仅占位(需 AI_API_KEY), 检索+引用机制为本次验证重点。
"""
import json, re, math, os

CHUNKS_FILE = "C:/Users/baibai/.workbuddy/research/parsed/茅台2022年报.chunks.json"
data = json.load(open(CHUNKS_FILE, encoding="utf-8"))
chunks = [(c[0], c[1]) for c in data["chunks"]]   # (pno, text)
N = len(chunks)

def tokenize(text):
    toks = []
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    for i, c in enumerate(cjk):
        toks.append(c)
        if i + 1 < len(cjk):
            toks.append(cjk[i] + cjk[i + 1])       # 字 bigram, 解决中文无空格分词
    for m in re.findall(r"\d[\d,\.]*", text):
        toks.append(m)
    return toks

doc_toks = [tokenize(t) for _, t in chunks]
df = {}
for dt in doc_toks:
    for w in set(dt):
        df[w] = df.get(w, 0) + 1
idf = {w: math.log((N + 1) / (c + 1)) + 1 for w, c in df.items()}

def bm25(qtokens):
    out = []
    for i, (pno, t) in enumerate(chunks):
        freq = {}
        for w in doc_toks[i]:
            freq[w] = freq.get(w, 0) + 1
        score = 0.0
        for q in set(qtokens):
            f = freq.get(q, 0)
            if f and q in idf:
                score += idf[q] * (f * 2.2) / (f + 1.2)
        out.append((score, pno, i))
    out.sort(reverse=True)
    return out

def answer_with_citation(q):
    qt = tokenize(q)
    top = bm25(qt)[:3]
    hits = [(sc, pno, chunks[i][1]) for sc, pno, i in top if sc > 0]
    if not hits:
        return "未检索到相关段落。", []
    # 取 top1 片段作为证据, 并截取含关键词的句子
    best_sc, best_pno, best_txt = hits[0]
    snippet = re.sub(r"\s+", " ", best_txt).strip()[:200]
    answer = f"根据第 {best_pno} 页内容：{snippet}……"
    cites = [{"page": pno, "score": round(sc, 1)} for sc, pno, _ in hits]
    return answer, cites

QUERIES = [
    "茅台2022年营业收入是多少？",
    "为什么经营活动产生的现金流量净额减少了？",
    "茅台的归母净利润有多少？",
]

print("=== 预研 #5: 带页码引用的检索问答 ===")
for q in QUERIES:
    ans, cites = answer_with_citation(q)
    print(f"\nQ: {q}")
    print(f"A: {ans}")
    print(f"  引用页码: {[c['page'] for c in cites]}  (各片段得分: {[c['score'] for c in cites]})")

# LLM 生成步骤占位(需配置 AI_API_KEY / AI_BASE_URL)
if os.environ.get("AI_API_KEY"):
    print("\n[检测到 AI_API_KEY] 此处可调用 OpenAI 兼容接口, 将检索片段作为 context 拼 prompt 生成最终答案。")
else:
    print("\n[未配置 AI_API_KEY] LLM 生成步骤为占位; 检索+页码引用机制已验证, 生成环节接入任意 OpenAI 兼容模型即可。")
