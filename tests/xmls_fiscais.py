"""XMLs fiscais fictícios para os testes: NF-e, NFC-e, CT-e, MDF-e, NFS-e e eventos.

Só têm as tags que os geradores de PDF usam. Os dados (empresas, CNPJs, endereços) são inventados.
"""
from __future__ import annotations

from pathlib import Path

NFE = "http://www.portalfiscal.inf.br/nfe"
CTE = "http://www.portalfiscal.inf.br/cte"
MDFE = "http://www.portalfiscal.inf.br/mdfe"
NFSE = "http://www.sped.fazenda.gov.br/nfse"

CNPJ_EMITENTE = "11222333000181"
ENDERECO = """
            <xLgr>RUA EXEMPLO</xLgr>
            <nro>100</nro>
            <xBairro>CENTRO</xBairro>
            <cMun>3550308</cMun>
            <xMun>SAO PAULO</xMun>
            <UF>SP</UF>
            <CEP>01001000</CEP>"""


def chave(modelo: int, numero: int, serie: int = 1, cnpj: str = CNPJ_EMITENTE) -> str:
    """Chave de acesso de 44 dígitos, com o dígito verificador calculado como na SEFAZ."""
    base = f"352601{cnpj}{modelo:02d}{serie:03d}{numero:09d}1{numero:08d}"
    pesos = [2, 3, 4, 5, 6, 7, 8, 9]
    soma = sum(int(d) * pesos[i % 8] for i, d in enumerate(reversed(base)))
    resto = soma % 11
    return base + str(0 if resto < 2 else 11 - resto)


def nfe(numero=1234, serie=1, emitente="EMPRESA EXEMPLO LTDA", modelo=55, cnpj=CNPJ_EMITENTE, protocolo=True) -> str:
    ch = chave(modelo, numero, serie, cnpj)
    supl = ""
    if modelo == 65:
        supl = """
    <infNFeSupl>
        <qrCode>https://www.exemplo.gov.br/nfce/qrcode?p=1</qrCode>
        <urlChave>https://www.exemplo.gov.br/nfce/consulta</urlChave>
    </infNFeSupl>"""
    nfe_xml = f"""<NFe xmlns="{NFE}">
    <infNFe versao="4.00" Id="NFe{ch}">
        <ide>
            <cUF>35</cUF><cNF>{numero:08d}</cNF><natOp>VENDA</natOp><mod>{modelo}</mod>
            <serie>{serie}</serie><nNF>{numero}</nNF><dhEmi>2026-01-15T10:00:00-03:00</dhEmi>
            <tpNF>1</tpNF><idDest>1</idDest><cMunFG>3550308</cMunFG><tpImp>{4 if modelo == 65 else 1}</tpImp>
            <tpEmis>1</tpEmis><cDV>{ch[-1]}</cDV><tpAmb>1</tpAmb><finNFe>1</finNFe><indFinal>1</indFinal>
            <indPres>1</indPres><procEmi>0</procEmi><verProc>1.0</verProc>
        </ide>
        <emit>
            <CNPJ>{cnpj}</CNPJ>
            <xNome>{emitente}</xNome>
            <enderEmit>{ENDERECO}
            </enderEmit>
            <IE>123456789012</IE>
            <CRT>3</CRT>
        </emit>
        <dest>
            <CNPJ>44555666000199</CNPJ>
            <xNome>CLIENTE EXEMPLO LTDA</xNome>
            <enderDest>{ENDERECO}
            </enderDest>
            <indIEDest>9</indIEDest>
        </dest>
        <det nItem="1">
            <prod>
                <cProd>001</cProd><cEAN>SEM GTIN</cEAN><xProd>PRODUTO EXEMPLO</xProd><NCM>96100000</NCM>
                <CFOP>5102</CFOP><uCom>UN</uCom><qCom>1.0000</qCom><vUnCom>100.00</vUnCom><vProd>100.00</vProd>
                <cEANTrib>SEM GTIN</cEANTrib><uTrib>UN</uTrib><qTrib>1.0000</qTrib><vUnTrib>100.00</vUnTrib>
                <indTot>1</indTot>
            </prod>
            <imposto>
                <ICMS><ICMS00><orig>0</orig><CST>00</CST><modBC>0</modBC><vBC>100.00</vBC>
                <pICMS>18.00</pICMS><vICMS>18.00</vICMS></ICMS00></ICMS>
                <PIS><PISNT><CST>07</CST></PISNT></PIS>
                <COFINS><COFINSNT><CST>07</CST></COFINSNT></COFINS>
            </imposto>
        </det>
        <total>
            <ICMSTot>
                <vBC>100.00</vBC><vICMS>18.00</vICMS><vICMSDeson>0.00</vICMSDeson><vFCP>0.00</vFCP>
                <vBCST>0.00</vBCST><vST>0.00</vST><vFCPST>0.00</vFCPST><vFCPSTRet>0.00</vFCPSTRet>
                <vProd>100.00</vProd><vFrete>0.00</vFrete><vSeg>0.00</vSeg><vDesc>0.00</vDesc><vII>0.00</vII>
                <vIPI>0.00</vIPI><vIPIDevol>0.00</vIPIDevol><vPIS>0.00</vPIS><vCOFINS>0.00</vCOFINS>
                <vOutro>0.00</vOutro><vNF>100.00</vNF>
            </ICMSTot>
        </total>
        <transp><modFrete>9</modFrete></transp>
        <pag><detPag><tPag>01</tPag><vPag>100.00</vPag></detPag></pag>
    </infNFe>{supl}
</NFe>"""
    if not protocolo:
        return f'<?xml version="1.0" encoding="UTF-8"?>\n{nfe_xml}'
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc versao="4.00" xmlns="{NFE}">
{nfe_xml}
<protNFe versao="4.00"><infProt>
    <tpAmb>1</tpAmb><verAplic>SP_NFE_PL009</verAplic><chNFe>{ch}</chNFe>
    <dhRecbto>2026-01-15T10:00:05-03:00</dhRecbto><nProt>135260000000001</nProt><cStat>100</cStat>
    <xMotivo>Autorizado o uso da NF-e</xMotivo>
</infProt></protNFe>
</nfeProc>"""


def cte(numero=567, serie=1, emitente="EXEMPLO TRANSPORTES LTDA", modelo=57) -> str:
    ch = chave(modelo, numero, serie)
    raiz = "CTeOS" if modelo == 67 else "CTe"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<{raiz} xmlns="{CTE}">
  <infCte versao="4.00" Id="CTe{ch}">
    <ide>
      <cUF>35</cUF><cCT>{numero:08d}</cCT><CFOP>5352</CFOP><natOp>PRESTACAO DE SERVICO</natOp>
      <mod>{modelo}</mod><serie>{serie}</serie><nCT>{numero}</nCT><dhEmi>2026-01-15T10:00:00-03:00</dhEmi>
      <tpImp>1</tpImp><tpEmis>1</tpEmis><cDV>{ch[-1]}</cDV><tpAmb>1</tpAmb><tpCTe>0</tpCTe><procEmi>0</procEmi>
      <verProc>1.0</verProc><cMunEnv>3550308</cMunEnv><xMunEnv>SAO PAULO</xMunEnv><UFEnv>SP</UFEnv>
      <modal>01</modal><tpServ>0</tpServ><cMunIni>3550308</cMunIni><xMunIni>SAO PAULO</xMunIni><UFIni>SP</UFIni>
      <cMunFim>3304557</cMunFim><xMunFim>RIO DE JANEIRO</xMunFim><UFFim>RJ</UFFim><retira>1</retira>
      <indIEToma>1</indIEToma><toma3><toma>0</toma></toma3>
    </ide>
    <emit>
      <CNPJ>{CNPJ_EMITENTE}</CNPJ><IE>123456789012</IE><xNome>{emitente}</xNome>
      <enderEmit>{ENDERECO}
      </enderEmit>
      <CRT>3</CRT>
    </emit>
    <rem>
      <CNPJ>44555666000199</CNPJ><IE>987654321098</IE><xNome>CLIENTE EXEMPLO LTDA</xNome>
      <enderReme>{ENDERECO}
      </enderReme>
    </rem>
    <dest>
      <CNPJ>77888999000155</CNPJ><IE>111222333444</IE><xNome>DESTINATARIO EXEMPLO LTDA</xNome>
      <enderDest>{ENDERECO}
      </enderDest>
    </dest>
    <vPrest><vTPrest>50.00</vTPrest><vRec>50.00</vRec><Comp><xNome>FRETE</xNome><vComp>50.00</vComp></Comp></vPrest>
    <imp><ICMS><ICMS00><CST>00</CST><vBC>50.00</vBC><pICMS>12.00</pICMS><vICMS>6.00</vICMS></ICMS00></ICMS></imp>
    <infCTeNorm>
      <infCarga>
        <vCarga>1000.00</vCarga><proPred>MERCADORIA EXEMPLO</proPred>
        <infQ><cUnid>01</cUnid><tpMed>PESO BRUTO</tpMed><qCarga>100.0000</qCarga></infQ>
      </infCarga>
      <infDoc><infNFe><chave>{chave(55, 1234)}</chave></infNFe></infDoc>
      <infModal versaoModal="4.00"><rodo><RNTRC>12345678</RNTRC></rodo></infModal>
    </infCTeNorm>
  </infCte>
</{raiz}>"""


def mdfe(numero=89, serie=1, emitente="EXEMPLO TRANSPORTES LTDA") -> str:
    ch = chave(58, numero, serie)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<MDFe xmlns="{MDFE}">
    <infMDFe versao="3.00" Id="MDFe{ch}">
        <ide>
            <cUF>35</cUF><tpAmb>1</tpAmb><tpEmit>2</tpEmit><mod>58</mod><serie>{serie}</serie>
            <nMDF>{numero}</nMDF><cMDF>{numero:08d}</cMDF><modal>1</modal><dhEmi>2026-01-15T10:00:00-03:00</dhEmi>
            <tpEmis>1</tpEmis><procEmi>0</procEmi><verProc>1.0</verProc><UFIni>SP</UFIni><UFFim>RJ</UFFim>
            <infMunCarrega><cMunCarrega>3550308</cMunCarrega><xMunCarrega>SAO PAULO</xMunCarrega></infMunCarrega>
        </ide>
        <emit>
            <CNPJ>{CNPJ_EMITENTE}</CNPJ><IE>123456789012</IE><xNome>{emitente}</xNome>
            <enderEmit>{ENDERECO}
            </enderEmit>
        </emit>
        <infModal versaoModal="3.00">
            <rodo><veicTracao><cInt>1</cInt><placa>ABC1D23</placa><tara>5000</tara><tpRod>01</tpRod>
            <tpCar>02</tpCar><UF>SP</UF></veicTracao></rodo>
        </infModal>
        <infDoc>
            <infMunDescarga>
                <cMunDescarga>3304557</cMunDescarga><xMunDescarga>RIO DE JANEIRO</xMunDescarga>
                <infNFe><chNFe>{chave(55, 1234)}</chNFe></infNFe>
            </infMunDescarga>
        </infDoc>
        <tot><qNFe>1</qNFe><vCarga>1000.00</vCarga><cUnid>01</cUnid><qCarga>100.0000</qCarga></tot>
    </infMDFe>
</MDFe>"""


def nfse(numero=42, emitente="EXEMPLO SERVICOS LTDA") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="{NFSE}">
    <infNFSe versao="1.01" Id="NFS3550308{CNPJ_EMITENTE}0000000000{numero:013d}00000000">
        <xLocEmi>SAO PAULO</xLocEmi><xLocPrestacao>SAO PAULO</xLocPrestacao><nNFSe>{numero}</nNFSe>
        <verAplic>1.0</verAplic><ambGer>1</ambGer><tpEmis>1</tpEmis><procEmi>1</procEmi><cStat>100</cStat>
        <dhProc>2026-01-15T10:00:00-03:00</dhProc><nDFSe>1</nDFSe>
        <emit><CNPJ>{CNPJ_EMITENTE}</CNPJ><xNome>{emitente}</xNome></emit>
        <valores><vLiq>500.00</vLiq></valores>
        <DPS versao="1.00">
            <infDPS Id="DPS{numero}">
                <tpAmb>1</tpAmb><dhEmi>2026-01-15T09:00:00-03:00</dhEmi><nDPS>{numero}</nDPS><serie>1</serie>
                <dCompet>2026-01-15</dCompet>
                <prest><CNPJ>{CNPJ_EMITENTE}</CNPJ></prest>
                <serv><cServ><cTribNac>010501</cTribNac><xDescServ>SERVICO DE EXEMPLO</xDescServ></cServ></serv>
                <valores><vServPrest><vServ>500.00</vServ></vServPrest></valores>
            </infDPS>
        </DPS>
    </infNFSe>
</NFSe>"""


def evento(chave_doc: str, tipo: str = "110110", sequencia: int = 1, documento: str = "nfe", c_stat="135") -> str:
    """Evento de NF-e ou CT-e: 110110 é carta de correção e 110111 é cancelamento."""
    ns, raiz, campo = (NFE, "procEventoNFe", "chNFe") if documento == "nfe" else (CTE, "procEventoCTe", "chCTe")
    detalhe = (
        "<descEvento>Carta de Correcao</descEvento><xCorrecao>Corrige o endereco do destinatario.</xCorrecao>"
        "<xCondUso>A Carta de Correcao e disciplinada pelo paragrafo 1o-A do art. 7o do Convenio S/N.</xCondUso>"
        if tipo == "110110" else
        "<descEvento>Cancelamento</descEvento><nProt>135260000000001</nProt><xJust>Erro na emissao da nota</xJust>"
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<{raiz} versao="1.00" xmlns="{ns}">
    <evento versao="1.00">
        <infEvento Id="ID{tipo}{chave_doc}{sequencia:02d}">
            <cOrgao>35</cOrgao><tpAmb>1</tpAmb><CNPJ>{CNPJ_EMITENTE}</CNPJ><{campo}>{chave_doc}</{campo}>
            <dhEvento>2026-01-16T10:00:00-03:00</dhEvento><tpEvento>{tipo}</tpEvento>
            <nSeqEvento>{sequencia}</nSeqEvento><verEvento>1.00</verEvento>
            <detEvento versao="1.00">{detalhe}</detEvento>
        </infEvento>
    </evento>
    <retEvento versao="1.00">
        <infEvento>
            <tpAmb>1</tpAmb><verAplic>1.0</verAplic><cOrgao>35</cOrgao><cStat>{c_stat}</cStat>
            <xMotivo>Evento registrado e vinculado</xMotivo><{campo}>{chave_doc}</{campo}><tpEvento>{tipo}</tpEvento>
            <nSeqEvento>{sequencia}</nSeqEvento><dhRegEvento>2026-01-16T10:00:05-03:00</dhRegEvento>
            <nProt>135260000000002</nProt>
        </infEvento>
    </retEvento>
</{raiz}>"""


def gravar(caminho: Path, conteudo: str, codificacao: str = "utf-8") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if codificacao != "utf-8":
        conteudo = conteudo.replace('encoding="UTF-8"', f'encoding="{codificacao.upper()}"', 1)
    caminho.write_bytes(conteudo.encode(codificacao))
    return caminho
