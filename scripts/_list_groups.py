import re, sys
sys.stdout.reconfigure(encoding='utf-8')
groups = set()
with open('lista_iptv.m3u', encoding='utf-8') as f:
    for line in f:
        m = re.search(r'group-title="([^"]+)"', line)
        if m: groups.add(m.group(1))
for g in sorted(groups): print(g)
