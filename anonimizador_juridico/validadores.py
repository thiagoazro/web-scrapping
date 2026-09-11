"""Validadores de documentos brasileiros.

São eles que transformam "sequência de 11 dígitos" em "CPF" com certeza
matemática — é o que dá à camada determinística uma precisão que nenhum
modelo de linguagem entrega sozinho.
"""

from __future__ import annotations

import re

_SO_DIGITOS = re.compile(r"\D")


def apenas_digitos(valor: str) -> str:
    return _SO_DIGITOS.sub("", valor)


def _digitos_repetidos(numero: str) -> bool:
    return len(set(numero)) == 1


def valida_cpf(valor: str) -> bool:
    num = apenas_digitos(valor)
    if len(num) != 11 or _digitos_repetidos(num):
        return False
    for tamanho in (9, 10):
        soma = sum(int(num[i]) * (tamanho + 1 - i) for i in range(tamanho))
        dv = (soma * 10) % 11
        dv = 0 if dv == 10 else dv
        if dv != int(num[tamanho]):
            return False
    return True


def valida_cnpj(valor: str) -> bool:
    num = apenas_digitos(valor)
    if len(num) != 14 or _digitos_repetidos(num):
        return False
    pesos1 = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    pesos2 = [6] + pesos1
    for pesos, pos in ((pesos1, 12), (pesos2, 13)):
        soma = sum(int(num[i]) * pesos[i] for i in range(pos))
        resto = soma % 11
        dv = 0 if resto < 2 else 11 - resto
        if dv != int(num[pos]):
            return False
    return True


def valida_pis(valor: str) -> bool:
    """PIS/PASEP/NIT — 11 dígitos com DV módulo 11."""
    num = apenas_digitos(valor)
    if len(num) != 11 or _digitos_repetidos(num):
        return False
    pesos = [3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    soma = sum(int(num[i]) * pesos[i] for i in range(10))
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    return dv == int(num[10])


def valida_processo_cnj(valor: str) -> bool:
    """Numeração única do CNJ (Res. 65/2008): NNNNNNN-DD.AAAA.J.TR.OOOO.

    O DV satisfaz: (numero_sem_dv * 100) mod 97 == 1.
    """
    num = apenas_digitos(valor)
    if len(num) != 20:
        return False
    sequencial, dv, resto = num[:7], num[7:9], num[9:]
    base = int(sequencial + resto + "00")
    return (98 - (base % 97)) == int(dv)


def valida_luhn(valor: str) -> bool:
    """Cartões de crédito/débito."""
    num = apenas_digitos(valor)
    if len(num) < 13 or len(num) > 19 or _digitos_repetidos(num):
        return False
    soma, alternar = 0, False
    for digito in reversed(num):
        d = int(digito)
        if alternar:
            d *= 2
            if d > 9:
                d -= 9
        soma += d
        alternar = not alternar
    return soma % 10 == 0


def valida_titulo_eleitor(valor: str) -> bool:
    """Título de eleitor: 12 dígitos (8 sequenciais + 2 de UF + 2 DV)."""
    num = apenas_digitos(valor)
    if len(num) != 12 or _digitos_repetidos(num):
        return False
    uf = int(num[8:10])
    if uf < 1 or uf > 28:
        return False
    soma = sum(int(num[i]) * (i + 2) for i in range(8))
    dv1 = soma % 11
    dv1 = 0 if dv1 == 10 else dv1
    if dv1 != int(num[10]):
        return False
    soma2 = int(num[8]) * 7 + int(num[9]) * 8 + dv1 * 9
    dv2 = soma2 % 11
    dv2 = 0 if dv2 == 10 else dv2
    return dv2 == int(num[11])


def valida_cnh(valor: str) -> bool:
    """CNH: 11 dígitos com dois DVs (módulo 11 com pesos decrescentes)."""
    num = apenas_digitos(valor)
    if len(num) != 11 or _digitos_repetidos(num):
        return False
    soma = sum(int(num[i]) * (9 - i) for i in range(9))
    dv1 = soma % 11
    incremento = 0
    if dv1 >= 10:
        dv1, incremento = 0, 2
    soma2 = sum(int(num[i]) * (1 + i) for i in range(9))
    dv2 = soma2 % 11
    dv2 = 0 if dv2 >= 10 else dv2
    dv2 = dv2 - incremento if dv2 - incremento >= 0 else dv2 - incremento + 11
    return dv1 == int(num[9]) and dv2 == int(num[10])


VALIDADORES = {
    "CPF": valida_cpf,
    "CNPJ": valida_cnpj,
    "PIS": valida_pis,
    "PROCESSO_CNJ": valida_processo_cnj,
    "CARTAO": valida_luhn,
    "TITULO_ELEITOR": valida_titulo_eleitor,
    "CNH": valida_cnh,
}
