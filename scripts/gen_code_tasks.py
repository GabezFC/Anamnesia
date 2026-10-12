"""ANA-039: deterministic `code` tasks for the routing benchmark -> benchmark/routing_tasks_code.json.

Each task = write a small pure-Python function; success = the hidden test script exits 0 inside the
sandboxed verifier (app.routing.verifiers.verify_tests_pass, ExecGuard allowlist, timeout cap, temp copy).
Every task ships a REFERENCE solution used by tests/test_ana039_code_tasks.py to prove the tests are
satisfiable (and that NULL_ECHO / EMPTY answers fail). Reference solutions are NOT written into the prompt.

  python scripts/gen_code_tasks.py            # (re)write the JSON
  python scripts/run_routing_benchmark.py --real --tasks benchmark/routing_tasks_code.json ...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = 1

# (name, signature, description, reference body, [(call_expr, expected_repr)], difficulty)
SPECS = [
    ("soma_pares", "soma_pares(nums)", "retorna a soma dos numeros pares da lista (0 se nao houver)",
     "return sum(n for n in nums if n % 2 == 0)", [("soma_pares([1,2,3,4])", "6"), ("soma_pares([])", "0"), ("soma_pares([1,3])", "0")], "easy"),
    ("inverte_palavras", "inverte_palavras(s)", "inverte a ORDEM das palavras de uma frase separada por espacos simples",
     "return ' '.join(reversed(s.split()))", [("inverte_palavras('a b c')", "'c b a'"), ("inverte_palavras('x')", "'x'")], "easy"),
    ("eh_palindromo", "eh_palindromo(s)", "True se s e palindromo ignorando maiusculas, espacos e pontuacao",
     "t=[c.lower() for c in s if c.isalnum()]\n    return t==t[::-1]", [("eh_palindromo('Anotaram a data da maratona')", "True"), ("eh_palindromo('abc')", "False"), ("eh_palindromo('A man, a plan, a canal: Panama')", "True")], "easy"),
    ("fatorial", "fatorial(n)", "fatorial de n>=0; levanta ValueError se n<0",
     "if n<0:\n        raise ValueError\n    r=1\n    for i in range(2,n+1):\n        r*=i\n    return r", [("fatorial(0)", "1"), ("fatorial(5)", "120")], "easy"),
    ("fibonacci", "fibonacci(n)", "n-esimo Fibonacci com fibonacci(0)=0 e fibonacci(1)=1",
     "a,b=0,1\n    for _ in range(n):\n        a,b=b,a+b\n    return a", [("fibonacci(0)", "0"), ("fibonacci(1)", "1"), ("fibonacci(10)", "55")], "easy"),
    ("conta_vogais", "conta_vogais(s)", "conta vogais (aeiou, sem acento, maiusculas contam)",
     "return sum(1 for c in s.lower() if c in 'aeiou')", [("conta_vogais('Abacaxi')", "4"), ("conta_vogais('xyz')", "0")], "easy"),
    ("remove_duplicados", "remove_duplicados(xs)", "remove duplicados preservando a ordem da primeira ocorrencia",
     "seen=set(); out=[]\n    for x in xs:\n        if x not in seen:\n            seen.add(x); out.append(x)\n    return out", [("remove_duplicados([3,1,3,2,1])", "[3, 1, 2]"), ("remove_duplicados([])", "[]")], "easy"),
    ("maximo_segundo", "maximo_segundo(xs)", "segundo maior VALOR distinto; None se houver menos de 2 valores distintos",
     "u=sorted(set(xs), reverse=True)\n    return u[1] if len(u)>1 else None", [("maximo_segundo([1,5,5,3])", "3"), ("maximo_segundo([2,2])", "None")], "medium"),
    ("rle", "rle(s)", "run-length encoding: 'aaabcc' -> 'a3b1c2'; string vazia -> ''",
     "out=[]; i=0\n    while i<len(s):\n        j=i\n        while j<len(s) and s[j]==s[i]:\n            j+=1\n        out.append(s[i]+str(j-i)); i=j\n    return ''.join(out)", [("rle('aaabcc')", "'a3b1c2'"), ("rle('')", "''")], "medium"),
    ("anagramas", "anagramas(a, b)", "True se a e b sao anagramas ignorando maiusculas e espacos",
     "f=lambda x: sorted(x.lower().replace(' ',''))\n    return f(a)==f(b)", [("anagramas('Amor','Roma')", "True"), ("anagramas('abc','abd')", "False"), ("anagramas('a b','ba')", "True")], "medium"),
    ("binaria", "binaria(xs, alvo)", "busca binaria em lista ordenada; retorna o indice ou -1",
     "lo,hi=0,len(xs)-1\n    while lo<=hi:\n        m=(lo+hi)//2\n        if xs[m]==alvo:\n            return m\n        if xs[m]<alvo:\n            lo=m+1\n        else:\n            hi=m-1\n    return -1", [("binaria([1,3,5,7],5)", "2"), ("binaria([1,3,5,7],4)", "-1"), ("binaria([],1)", "-1")], "medium"),
    ("merge_ordenado", "merge_ordenado(a, b)", "intercala duas listas ja ordenadas em uma lista ordenada",
     "i=j=0; out=[]\n    while i<len(a) and j<len(b):\n        if a[i]<=b[j]:\n            out.append(a[i]); i+=1\n        else:\n            out.append(b[j]); j+=1\n    return out+a[i:]+b[j:]", [("merge_ordenado([1,4],[2,3,5])", "[1, 2, 3, 4, 5]"), ("merge_ordenado([],[1])", "[1]")], "medium"),
    ("parenteses", "parenteses(s)", "True se os parenteses/colchetes/chaves de s estao balanceados",
     "pairs={')':'(',']':'[','}':'{'}; st=[]\n    for c in s:\n        if c in '([{':\n            st.append(c)\n        elif c in pairs:\n            if not st or st.pop()!=pairs[c]:\n                return False\n    return not st", [("parenteses('([]{})')", "True"), ("parenteses('(]')", "False"), ("parenteses('((')", "False")], "medium"),
    ("mdc", "mdc(a, b)", "maximo divisor comum de inteiros positivos",
     "while b:\n        a,b=b,a%b\n    return a", [("mdc(12,18)", "6"), ("mdc(7,13)", "1")], "easy"),
    ("primos_ate", "primos_ate(n)", "lista de primos <= n em ordem crescente",
     "return [p for p in range(2,n+1) if all(p%d for d in range(2,int(p**0.5)+1))]", [("primos_ate(10)", "[2, 3, 5, 7]"), ("primos_ate(1)", "[]")], "medium"),
    ("transpoe", "transpoe(m)", "transposta de uma matriz (lista de listas retangular); [] -> []",
     "return [list(r) for r in zip(*m)]", [("transpoe([[1,2,3],[4,5,6]])", "[[1, 4], [2, 5], [3, 6]]"), ("transpoe([])", "[]")], "medium"),
    ("camel_para_snake", "camel_para_snake(s)", "converte camelCase para snake_case (letras maiusculas viram _minuscula)",
     "out=''\n    for c in s:\n        out += ('_'+c.lower()) if c.isupper() else c\n    return out", [("camel_para_snake('minhaVariavelLonga')", "'minha_variavel_longa'"), ("camel_para_snake('abc')", "'abc'")], "easy"),
    ("agrupa_por_tamanho", "agrupa_por_tamanho(palavras)", "dict {tamanho: [palavras na ordem de entrada]}",
     "d={}\n    for p in palavras:\n        d.setdefault(len(p),[]).append(p)\n    return d", [("agrupa_por_tamanho(['a','bb','c','dd'])", "{1: ['a', 'c'], 2: ['bb', 'dd']}")], "medium"),
    ("intervalos", "intervalos(xs)", "mescla intervalos [a,b] sobrepostos/adjacentes (b>=proximo a) e retorna lista ordenada de listas",
     "out=[]\n    for a,b in sorted(xs):\n        if out and a<=out[-1][1]:\n            out[-1][1]=max(out[-1][1],b)\n        else:\n            out.append([a,b])\n    return out", [("intervalos([[1,3],[2,6],[8,10]])", "[[1, 6], [8, 10]]"), ("intervalos([[1,2],[2,3]])", "[[1, 3]]"), ("intervalos([])", "[]")], "hard"),
    ("lru_get_set", "lru_simula(capacidade, ops)", "simula cache LRU: ops = lista de ('set',k,v) ou ('get',k); retorna lista com o resultado de cada get (None se ausente)",
     "from collections import OrderedDict\n    c=OrderedDict(); out=[]\n    for op in ops:\n        if op[0]=='set':\n            c[op[1]]=op[2]; c.move_to_end(op[1])\n            if len(c)>capacidade:\n                c.popitem(last=False)\n        else:\n            if op[1] in c:\n                c.move_to_end(op[1]); out.append(c[op[1]])\n            else:\n                out.append(None)\n    return out", [("lru_simula(2,[('set','a',1),('set','b',2),('get','a'),('set','c',3),('get','b'),('get','c')])", "[1, None, 3]")], "hard"),
    ("romano", "romano(n)", "converte inteiro 1..3999 para numeral romano",
     "t=[(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),(50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]\n    out=''\n    for v,s in t:\n        while n>=v:\n            out+=s; n-=v\n    return out", [("romano(4)", "'IV'"), ("romano(1994)", "'MCMXCIV'"), ("romano(58)", "'LVIII'")], "hard"),
    ("duas_somas", "duas_somas(xs, alvo)", "retorna o par de INDICES (i, j), i<j, com xs[i]+xs[j]==alvo, menor i primeiro; None se nao existir",
     "for i in range(len(xs)):\n        for j in range(i+1,len(xs)):\n            if xs[i]+xs[j]==alvo:\n                return (i,j)\n    return None", [("duas_somas([2,7,11,15],9)", "(0, 1)"), ("duas_somas([1,2],10)", "None")], "medium"),
    ("flatten", "achata(x)", "achata listas aninhadas em profundidade arbitraria (apenas listas) em uma lista simples",
     "out=[]\n    for e in x:\n        if isinstance(e,list):\n            out.extend(achata(e))\n        else:\n            out.append(e)\n    return out", [("achata([1,[2,[3,[4]]],5])", "[1, 2, 3, 4, 5]"), ("achata([])", "[]")], "hard"),
]


def _tests(sig: str, cases) -> str:
    lines = ["from solution import *", "import sys", "fails = []"]
    for call, exp in cases:
        lines.append(f"try:\n    got = {call}\nexcept Exception as e:\n    got = ('EXC', type(e).__name__)\n"
                     f"if got != {exp}:\n    fails.append(({call!r}, got))")
    lines.append("sys.exit(1 if fails else 0)")
    return "\n".join(lines) + "\n"


def build() -> dict:
    tasks = []
    for i, (name, sig, desc, body, cases, diff) in enumerate(SPECS, 1):
        ref = f"def {sig}:\n    {body}\n"
        tasks.append({
            "id": f"rt-code{i:03d}", "kind": "code", "difficulty_label": diff, "risk": "low",
            "query": (f"Escreva em Python a funcao `{sig}` que {desc}. "
                      "Responda APENAS com o codigo da funcao (sem testes, sem explicacao)."),
            "ground_truth": {"function": sig.split("(")[0], "reference": ref},
            "verifier": {"type": "tests_pass", "tests": _tests(sig, cases), "timeout_s": 20},
        })
    return {"seed": 0, "version": VERSION, "tasks": tasks}


def main() -> int:
    out = ROOT / "benchmark" / "routing_tasks_code.json"
    out.write_text(json.dumps(build(), ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote", out, len(SPECS), "tasks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
