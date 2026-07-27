# -*- coding: utf-8 -*-
import fitz, json
PY="C:/Users/baibai/600519_年报_1216281757.pdf"
doc=fitz.open(PY)
# 正确 API: get_toc()
try:
    toc=doc.get_toc()
    print("TOC 节点数:", len(toc))
    for lvl,ttl,pg in toc[:10]:
        print(f"  {'  '*(lvl-1)}- {ttl} -> 第{pg}页")
except Exception as e:
    print("get_toc 错误:", e)

chunks=json.load(open("C:/Users/baibai/.workbuddy/research/parsed/茅台2022年报.chunks.json",encoding="utf-8"))["chunks"]
for pno,txt in chunks:
    if 4<=pno<=8:
        for kw in ["净利润","现金流","归属于","营业收入"]:
            i=txt.find(kw)
            if i!=-1:
                print(f"\n-- 第{pno}页 命中 '{kw}' @ {i} --")
                print(repr(txt[max(0,i-30):i+160]))
