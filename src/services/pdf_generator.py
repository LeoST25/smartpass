import io
from datetime import datetime
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from src.services.map_generator import gerar_imagem_mapa_rota


def _rota_para_mapa_pdf(dados_calculo: dict) -> dict | None:
    """Extrai as pernas da rota para desenhar o traçado real no mapa do PDF.

    Procura as ``legs`` no contrato principal e, na ausência, nas rotas do
    comparativo (mais rápida / mais econômica).

    Args:
        dados_calculo: Dicionário com os dados do cálculo (inclui ``legs`` e
            ``comparativo`` quando disponíveis).

    Returns:
        dict | None: Dicionário com ``legs`` para o mapa, ou ``None`` quando
        não há geometria disponível (o mapa usará o traçado fallback).
    """
    if not isinstance(dados_calculo, dict):
        return None

    legs = dados_calculo.get("legs")
    if legs:
        return {"legs": legs}

    comparativo = dados_calculo.get("comparativo")
    if isinstance(comparativo, dict):
        for chave in ("rota_mais_economica", "rota_mais_rapida"):
            rota = comparativo.get(chave)
            if isinstance(rota, dict) and rota.get("legs"):
                return {"legs": rota["legs"]}
    return None

def gerar_pdf_evidencia(dados_candidato, tipo_beneficio, dados_calculo, coords=None):
    """
    Gera um relatório em PDF contendo o resumo do benefício e a evidência cartográfica do trajeto.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'TitleStyle', parent=styles['Heading1'],
        fontSize=18, leading=22, textColor=colors.HexColor('#1E3A8A')
    )
    
    subtitle_style = ParagraphStyle(
        'SubTitleStyle', parent=styles['Normal'],
        fontSize=10, textColor=colors.HexColor('#4B5563')
    )
    
    heading_style = ParagraphStyle(
        'SectionHeading', parent=styles['Heading2'],
        fontSize=12, leading=16, textColor=colors.HexColor('#1E3A8A'),
        spaceBefore=10, spaceAfter=5
    )

    # 1. Cabeçalho
    story.append(Paragraph("SmartPass - Evidência de Admissão", title_style))
    story.append(Paragraph(f"Relatório de Trajeto & Tarifas | Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}", subtitle_style))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#CBD5E1'), spaceAfter=12))

    # 2. Dados do Colaborador
    story.append(Paragraph("1. Dados do Colaborador & Processo", heading_style))
    tabela_candidato_data = [
        [Paragraph("<b>Nome:</b>", styles['Normal']), Paragraph(dados_candidato.get('nome', 'N/A'), styles['Normal'])],
        [Paragraph("<b>Cargo:</b>", styles['Normal']), Paragraph(dados_candidato.get('cargo', 'N/A'), styles['Normal'])],
        [Paragraph("<b>Empresa / Centro de Custo:</b>", styles['Normal']), Paragraph(dados_candidato.get('centro_custo', 'N/A'), styles['Normal'])],
        [Paragraph("<b>Modalidade Solicitada:</b>", styles['Normal']), Paragraph(tipo_beneficio, styles['Normal'])]
    ]
    
    tabela_candidato = Table(tabela_candidato_data, colWidths=[160, 380])
    tabela_candidato.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(tabela_candidato)
    story.append(Spacer(1, 10))

    # 3. Resumo da Apuração
    story.append(Paragraph(f"2. Resumo da Apuração ({tipo_beneficio})", heading_style))

    # Bloco comparativo quando disponível (motor fare_engine)
    comparativo = dados_calculo.get("comparativo")
    if comparativo and isinstance(comparativo, dict) and comparativo.get("rota_mais_rapida"):
        rapida = comparativo.get("rota_mais_rapida") or {}
        economica = comparativo.get("rota_mais_economica")
        economia = comparativo.get("economia_mensal", 0)
        story.append(Paragraph("Comparativo — Mais Rápida vs Mais Econômica", heading_style))
        comp_data = [
            ["Critério", "Mais Rápida", "Mais Econômica"],
            [
                "Custo por trecho (1 sentido)",
                f"R$ {rapida.get('custo_trecho', 0):.2f}",
                f"R$ {economica.get('custo_trecho', 0):.2f}" if economica else "— (nenhuma elegível)",
            ],
            [
                "Custo diário (ida+volta)",
                f"R$ {rapida.get('custo_diario', 0):.2f}",
                f"R$ {economica.get('custo_diario', 0):.2f}" if economica else "—",
            ],
            [
                "Custo mensal",
                f"R$ {rapida.get('custo_mensal', 0):.2f}",
                f"R$ {economica.get('custo_mensal', 0):.2f}" if economica else "—",
            ],
            ["Economia mensal gerada", "", f"R$ {economia:.2f}"],
        ]
        # Ajusta dias úteis no rótulo se disponível
        dias = rapida.get("dias_uteis") or dados_calculo.get("dias_uteis") or 22
        comp_data[3][0] = f"Custo mensal ({dias} dias)"
        tabela_comp = Table(comp_data, colWidths=[160, 140, 240])
        tabela_comp.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
            ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#ECFDF5')),
            ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(tabela_comp)
        story.append(Spacer(1, 6))
        # Detalhamento tarifário da rota econômica (ou rápida se empate)
        rota_ref = economica if economica else rapida
        if rota_ref.get("detalhamento_tarifario"):
            story.append(Paragraph("Detalhamento Tarifário — Rota de Referência (Econômica quando disponível)", heading_style))
            for item in rota_ref["detalhamento_tarifario"]:
                story.append(Paragraph(f"• {escape(str(item))}", styles['Normal']))
            story.append(Spacer(1, 6))

    if "Vale-Combustível" in tipo_beneficio:
        tabela_resumo_data = [
            ["Item", "Valor / Descrição"],
            ["Endereço Origem", dados_calculo.get('origem', 'N/A')],
            ["Endereço Destino", dados_calculo.get('destino', 'N/A')],
            ["Distância Calculada (OSRM)", f"{dados_calculo.get('distancia_km', 0)} km"],
            ["Valor do KM Contratado", f"R$ {dados_calculo.get('valor_km', 0):.2f}"],
            ["Custo Total Estimado", f"R$ {dados_calculo.get('custo_total', 0):.2f}"]
        ]
        
        tabela_resumo = Table(tabela_resumo_data, colWidths=[200, 340])
        tabela_resumo.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (1,0), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0,0), (1,0), colors.whitesmoke),
            ('FONTNAME', (0,0), (1,0), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(tabela_resumo)
    else:
        # Vale-Transporte — tabela enriquecida com operadora/fonte/confirmada
        lin_headers = ["Linha / Modal", "Operadora", "Código", "Tarifa Un.", "Fonte", "Status"]
        tabela_vt_data = [
            ["Endereço Origem", dados_calculo.get('origem', 'N/A'), "", "", "", ""],
            ["Endereço Destino", dados_calculo.get('destino', 'N/A'), "", "", "", ""],
            lin_headers
        ]

        resumo_trajeto = dados_calculo.get("resumo_trajeto")
        if resumo_trajeto:
            story.append(Paragraph("Resumo do trajeto", heading_style))
            story.append(Paragraph(escape(resumo_trajeto), styles['Normal']))
            story.append(Spacer(1, 6))
        
        for det in dados_calculo.get('detalhes', []):
            status = "✅ Confirmada" if det.get("tarifa_confirmada") else "⚠️ Estimativa"
            fonte_curta = (det.get("fonte") or "—")[:32]
            tabela_vt_data.append([
                Paragraph(escape(str(det.get('linha', 'N/A'))), styles['Normal']),
                Paragraph(escape(str(det.get('operadora', '—'))), styles['Normal']),
                Paragraph(escape(str(det.get('codigo_linha', '—'))), styles['Normal']),
                f"R$ {det.get('valor_unitario', 0):.2f}",
                Paragraph(escape(fonte_curta), styles['Normal']),
                status,
            ])
            
        dias_label = dados_calculo.get("dias_uteis") or 22
        tabela_vt_data.append(["TOTAL DIÁRIO (ida+volta)", "", "", f"R$ {dados_calculo.get('custo_diario', 0):.2f}", "", ""])
        tabela_vt_data.append([f"ESTIMATIVA MENSAL ({dias_label} dias)", "", "", f"R$ {dados_calculo.get('custo_mensal', 0):.2f}", "", ""])

        tabela_vt = Table(tabela_vt_data, colWidths=[150, 90, 55, 65, 110, 70], repeatRows=3)
        tabela_vt.setStyle(TableStyle([
            ('SPAN', (1,0), (-1,0)),
            ('SPAN', (1,1), (-1,1)),
            ('BACKGROUND', (0,2), (-1,2), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0,2), (-1,2), colors.whitesmoke),
            ('FONTNAME', (0,2), (-1,2), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('BACKGROUND', (0,-2), (-1,-1), colors.HexColor('#F1F5F9')),
            ('FONTNAME', (0,-2), (-1,-1), 'Helvetica-Bold'),
            ('PADDING', (0,0), (-1,-1), 4),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('FONTSIZE', (0,0), (-1,-1), 7),
        ]))
        story.append(tabela_vt)
        # alerta de tarifas não confirmadas
        pend = [d for d in dados_calculo.get('detalhes', []) if not d.get("tarifa_confirmada")]
        if pend:
            story.append(Spacer(1, 6))
            story.append(Paragraph(f"<b>⚠️ Atenção:</b> {len(pend)} linha(s) com tarifa estimada — confirmar valor oficial junto à operadora/ARTESP: " + ", ".join([escape(f"{d.get('codigo_linha') or d.get('linha')} ({d.get('operadora')})") for d in pend]), styles['Normal']))
            story.append(Spacer(1, 4))

    story.append(Spacer(1, 8))

    # 3b. Detalhamento tarifário quando fare_engine presente (sem comparativo)
    if not comparativo and dados_calculo.get("detalhamento_tarifario"):
        story.append(Paragraph("Detalhamento Tarifário (Integração BU/TOP)", heading_style))
        for item in dados_calculo["detalhamento_tarifario"]:
            story.append(Paragraph(f"• {escape(str(item))}", styles['Normal']))
        story.append(Spacer(1, 6))

    # 3c. Memória de Cálculo / Auditoria (LGPD stateless)
    memoria = dados_calculo.get("memoria_calculo") or (comparativo.get("memoria_calculo") if comparativo else None)
    justificativa = dados_calculo.get("justificativa") or (comparativo.get("justificativa") if comparativo else None)
    if memoria:
        story.append(Paragraph("Memória de Cálculo / Auditoria", heading_style))
        for linha in memoria:
            story.append(Paragraph(f"• {escape(str(linha))}", styles['Normal']))
        if justificativa:
            story.append(Spacer(1, 4))
            story.append(Paragraph(f"<b>Justificativa:</b> {escape(str(justificativa))}", styles['Normal']))
        story.append(Spacer(1, 8))

    # 3d. Rateio CLT — Lei 7.418/85 (6% sobre salário-base) — quadro Empresa vs Colaborador
    viab = dados_calculo.get("viabilidade_clt")
    if viab and isinstance(viab, dict) and viab.get("sucesso"):
        salario_pdf = dados_calculo.get("salario_base")
        # só exibe quadro quando salário foi informado (>0) — evita rateio zerado não informativo
        if salario_pdf and float(salario_pdf) > 0:
            story.append(Paragraph("Rateio CLT — Lei 7.418/85 (Teto 6% sobre Salário-Base)", heading_style))
            custo_m = dados_calculo.get("custo_mensal", 0)
            teto = viab.get("teto_desconto_6_pct", 0)
            desc = viab.get("desconto_colaborador", 0)
            cust = viab.get("custeio_empresa", 0)
            status = "VT Vantajoso" if viab.get("vt_vantajoso") else "Alerta RH — não vantajoso"
            tabela_clt_data = [
                ["Componente", "Valor (R$)"],
                ["Salário Base informado", f"R$ {float(salario_pdf):.2f}"],
                ["Teto desconto 6% (CLT)", f"R$ {float(teto):.2f}"],
                ["Custo mensal VT", f"R$ {float(custo_m):.2f}"],
                ["Desconto colaborador (até teto)", f"R$ {float(desc):.2f}"],
                ["Subsídio empresa (excedente)", f"R$ {float(cust):.2f}"],
                ["Status viabilidade", status],
            ]
            tabela_clt = Table(tabela_clt_data, colWidths=[260, 280])
            tabela_clt.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1E3A8A')),
                ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
                ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
                ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
                ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#EFF6FF') if viab.get("vt_vantajoso") else colors.HexColor('#FEF3C7')),
                ('FONTNAME', (0,-1), (-1,-1), 'Helvetica-Bold'),
                ('PADDING', (0,0), (-1,-1), 5),
            ]))
            story.append(tabela_clt)
            story.append(Spacer(1, 6))
            story.append(Paragraph(f"<b>Recomendação:</b> {escape(str(viab.get('recomendacao','')))}", styles['Normal']))
            story.append(Spacer(1, 4))
            for linha in viab.get("memoria_calculo", []):
                story.append(Paragraph(f"• {escape(str(linha))}", styles['Normal']))
            story.append(Spacer(1, 4))
            story.append(Paragraph("<i>Base legal: art.4º, parágrafo único, Lei 7.418/85 — desconto máximo de 6% sobre salário-base; excedente custeado pelo empregador.</i>", styles['Normal']))
            story.append(Spacer(1, 8))

    story.append(Spacer(1, 10))

    # 4. Evidência Cartográfica do Trajeto (Substitui Termos de Assinatura)
    story.append(Paragraph("3. Evidência Cartográfica Auditável" if not memoria else "4. Evidência Cartográfica Auditável", heading_style))
    
    if coords and len(coords) == 4:
        lat_o, lon_o, lat_d, lon_d = coords
        # Usa a geometria real por trecho quando disponível (OTP) para desenhar
        # o traçado destacado sobre os tiles urbanos; caso contrário, cai no
        # traçado rodoviário/linha reta com fallback offline.
        rota_para_mapa = _rota_para_mapa_pdf(dados_calculo)
        img_buffer = gerar_imagem_mapa_rota(
            lat_o, lon_o, lat_d, lon_d, rota_dados=rota_para_mapa
        )
        story.append(Image(img_buffer, width=540, height=270))
    else:
        story.append(Paragraph("<i>Evidência cartográfica indisponível para esta consulta.</i>", styles['Normal']))

    # Constrói o PDF
    doc.build(story)
    buffer.seek(0)
    return buffer


def _sentido_para_mapa_pdf(opcao_selecionada: dict | None) -> dict | None:
    """Extrai as pernas da ida (referência) para o mapa estático do comprovante."""
    if not isinstance(opcao_selecionada, dict):
        return None
    ida = opcao_selecionada.get("ida") or {}
    legs = ida.get("legs")
    if legs:
        return {"legs": legs}
    volta = opcao_selecionada.get("volta") or {}
    if volta.get("legs"):
        return {"legs": volta["legs"]}
    return None


def _timeline_sentido(story, styles, sentido: dict, titulo: str, colors) -> None:
    """Renderiza a timeline de um sentido (ida/volta) com valor oficial por condução."""
    from reportlab.lib import colors as _colors

    story.append(Paragraph(titulo, styles["heading_style"]))

    legs_transito = sentido.get("legs_transito") or [
        leg for leg in (sentido.get("legs") or []) if leg.get("route") or leg.get("linha")
    ]
    detalhes = sentido.get("detalhes") or []

    if not legs_transito:
        story.append(Paragraph("<i>Sem pernas de transporte neste sentido.</i>", styles["Normal"]))
        story.append(Spacer(1, 6))
        return

    tabela = [[
        "Condução", "Operadora", "Horário", "Tarifa oficial", "Status"
    ]]
    for idx, leg in enumerate(legs_transito):
        rota = leg.get("route") or {}
        linha = (
            rota.get("shortName")
            or leg.get("linha")
            or leg.get("codigo_linha")
            or "—"
        )
        operadora = (leg.get("agency") or {}).get("name") or (rota.get("agency") or {}).get("name") or "—"
        horario = leg.get("horario_inicio") or "—"

        detalhe = detalhes[idx] if idx < len(detalhes) else {}
        valor = detalhe.get("valor_unitario")
        valor_txt = f"R$ {float(valor):.2f}" if valor is not None else "—"
        status = "✅ Confirmada" if detalhe.get("tarifa_confirmada") else ("⚠️ Estimativa" if detalhe else "—")

        tabela.append([
            Paragraph(escape(str(linha)), styles["Normal"]),
            Paragraph(escape(str(operadora)), styles["Normal"]),
            Paragraph(escape(str(horario)), styles["Normal"]),
            valor_txt,
            status,
        ])

    custo_trecho = sentido.get("custo_trecho", 0)
    tabela.append(["TOTAL DO SENTIDO", "", "", f"R$ {float(custo_trecho):.2f}", ""])

    tbl = Table(tabela, colWidths=[130, 130, 70, 110, 100])
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _colors.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), _colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, _colors.HexColor("#CBD5E1")),
        ("BACKGROUND", (0, -1), (-1, -1), _colors.HexColor("#F1F5F9")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("PADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(tbl)
    story.append(Spacer(1, 8))


def gerar_pdf_comprovante(
    dados_candidato: dict,
    dados_calculo: dict,
    coords=None,
    opcao_selecionada: dict | None = None,
    dados_assinatura: dict | None = None,
):
    """Gera o Comprovante de Vale-Transporte (Assinatura) com timeline Ida/Volta.

    Roteirizador individual: exibe a jornada separada em Ida (entrada) e Volta
    (saída), com o valor oficial de cada condução, custo diário/mensal, mapa
    estático, memória de cálculo e bloco de assinatura (Colaborador + RH).

    Args:
        dados_candidato: Dados do colaborador (nome, cargo, centro_custo).
        dados_calculo: Metadados do cálculo (origem, destino, horários, dias úteis,
            custos, viabilidade_clt, salario_base, memoria_calculo, justificativa).
        coords: Tupla (lat_o, lon_o, lat_d, lon_d) para o mapa.
        opcao_selecionada: Opção ranqueada (ida/volta) escolhida na UI.
        dados_assinatura: Dados para o bloco de assinatura (nome, cargo, cpf).

    Returns:
        io.BytesIO: Buffer PDF em memória (LGPD stateless).
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36,
    )

    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "TitleStyle", parent=styles["Heading1"],
        fontSize=18, leading=22, textColor=colors.HexColor("#1E3A8A"),
    )
    subtitle_style = ParagraphStyle(
        "SubTitleStyle", parent=styles["Normal"],
        fontSize=10, textColor=colors.HexColor("#4B5563"),
    )
    heading_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"],
        fontSize=12, leading=16, textColor=colors.HexColor("#1E3A8A"),
        spaceBefore=10, spaceAfter=5,
    )
    # expõe heading_style para o helper de timeline
    _styles = {
        "heading_style": heading_style,
        "Normal": styles["Normal"],
    }

    opcao = opcao_selecionada or {}

    # 1. Cabeçalho
    story.append(Paragraph("SmartPass — Comprovante de Vale-Transporte", title_style))
    story.append(Paragraph(
        f"Roteirizador Individual (Ida + Volta) | Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}",
        subtitle_style,
    ))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#CBD5E1"), spaceAfter=12))

    # 2. Dados do colaborador & processo
    story.append(Paragraph("1. Dados do Colaborador & Processo", heading_style))
    assinatura = dados_assinatura or {}
    tabela_candidato_data = [
        [Paragraph("<b>Nome:</b>", styles["Normal"]), Paragraph(escape(str(assinatura.get("nome") or dados_candidato.get("nome", "N/A"))), styles["Normal"])],
        [Paragraph("<b>Cargo:</b>", styles["Normal"]), Paragraph(escape(str(assinatura.get("cargo") or dados_candidato.get("cargo", "N/A"))), styles["Normal"])],
        [Paragraph("<b>Empresa / Centro de Custo:</b>", styles["Normal"]), Paragraph(escape(str(dados_candidato.get("centro_custo", "N/A"))), styles["Normal"])],
        [Paragraph("<b>Modalidade:</b>", styles["Normal"]), Paragraph("Vale-Transporte", styles["Normal"])],
    ]
    tabela_candidato = Table(tabela_candidato_data, colWidths=[160, 380])
    tabela_candidato.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tabela_candidato)
    story.append(Spacer(1, 10))

    # 3. Resumo da apuração
    story.append(Paragraph("2. Resumo da Apuração", heading_style))
    dias = dados_calculo.get("dias_uteis") or 22
    horario_entrada = dados_calculo.get("horario_entrada", "08:00")
    horario_saida = dados_calculo.get("horario_saida", "18:00")
    tabela_resumo = Table([
        ["Item", "Valor / Descrição"],
        ["Endereço Origem", escape(str(dados_calculo.get("origem", "N/A")))],
        ["Endereço Destino", escape(str(dados_calculo.get("destino", "N/A")))],
        ["Horário de entrada", horario_entrada],
        ["Horário de saída", horario_saida],
        ["Dias úteis", str(dias)],
        ["Custo diário (ida+volta)", f"R$ {float(opcao.get('custo_diario', 0) or 0):.2f}"],
        [f"Estimativa mensal ({dias} dias)", f"R$ {float(opcao.get('custo_mensal', 0) or 0):.2f}"],
    ], colWidths=[200, 340])
    tabela_resumo.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tabela_resumo)
    story.append(Spacer(1, 10))

    # 4. Jornada (Ida + Volta)
    story.append(Paragraph("3. Detalhamento da Jornada", heading_style))
    ida = opcao.get("ida") or {}
    volta = opcao.get("volta") or {}
    _timeline_sentido(story, _styles, ida, f"Ida — chegada até {horario_entrada}", colors)
    _timeline_sentido(story, _styles, volta, f"Volta — saída a partir de {horario_saida}", colors)

    # 5. Rateio CLT
    viab = dados_calculo.get("viabilidade_clt")
    salario_pdf = dados_calculo.get("salario_base")
    if viab and isinstance(viab, dict) and viab.get("sucesso") and salario_pdf and float(salario_pdf) > 0:
        story.append(Paragraph("4. Rateio CLT — Lei 7.418/85 (Teto 6%)", heading_style))
        custo_m = opcao.get("custo_mensal", 0)
        teto = viab.get("teto_desconto_6_pct", 0)
        desc = viab.get("desconto_colaborador", 0)
        cust = viab.get("custeio_empresa", 0)
        tabela_clt_data = [
            ["Componente", "Valor (R$)"],
            ["Salário Base informado", f"R$ {float(salario_pdf):.2f}"],
            ["Teto desconto 6% (CLT)", f"R$ {float(teto):.2f}"],
            ["Custo mensal VT", f"R$ {float(custo_m):.2f}"],
            ["Desconto colaborador (até teto)", f"R$ {float(desc):.2f}"],
            ["Subsídio empresa (excedente)", f"R$ {float(cust):.2f}"],
        ]
        tabela_clt = Table(tabela_clt_data, colWidths=[260, 280])
        tabela_clt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(tabela_clt)
        story.append(Spacer(1, 4))
        story.append(Paragraph(f"<b>Recomendação:</b> {escape(str(viab.get('recomendacao', '')))}", styles["Normal"]))
        story.append(Spacer(1, 6))

    # 6. Memória de cálculo / auditoria
    memoria = dados_calculo.get("memoria_calculo") or []
    if memoria:
        story.append(Paragraph("Memória de Cálculo / Auditoria", heading_style))
        for linha in memoria:
            story.append(Paragraph(f"• {escape(str(linha))}", styles["Normal"]))
        story.append(Spacer(1, 8))

    # 7. Evidência cartográfica
    story.append(Paragraph("Evidência Cartográfica Auditável", heading_style))
    if coords and len(coords) == 4:
        lat_o, lon_o, lat_d, lon_d = coords
        img_buffer = gerar_imagem_mapa_rota(
            lat_o, lon_o, lat_d, lon_d, rota_dados=_sentido_para_mapa_pdf(opcao)
        )
        story.append(Image(img_buffer, width=540, height=270))
    else:
        story.append(Paragraph("<i>Evidência cartográfica indisponível para esta consulta.</i>", styles["Normal"]))

    story.append(Spacer(1, 18))

    # 8. Bloco de assinatura
    story.append(Paragraph("Assinaturas", heading_style))
    data_assinatura = datetime.now().strftime("%d/%m/%Y")
    linha1 = f"{escape(str(assinatura.get('nome') or dados_candidato.get('nome', 'Colaborador')))} — CPF: {escape(str(assinatura.get('cpf', '___________')))}"
    tabela_assinatura = Table([
        [Paragraph("Assinatura do Colaborador", styles["Normal"]), Paragraph("Assinatura do RH / Empresa", styles["Normal"])],
        ["", ""],
        ["", ""],
        [Paragraph(f"Data: {data_assinatura}", styles["Normal"]), Paragraph(f"Data: {data_assinatura}", styles["Normal"])],
    ], colWidths=[270, 270])
    tabela_assinatura.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
        ("PADDING", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F8FAFC")),
    ]))
    story.append(tabela_assinatura)
    story.append(Spacer(1, 6))
    story.append(Paragraph("<i>Base legal: art.4º, parágrafo único, Lei 7.418/85 — desconto máximo de 6% sobre o salário-base; excedente custeado pelo empregador.</i>", styles["Normal"]))

    doc.build(story)
    buffer.seek(0)
    return buffer
