import io
from datetime import datetime
from xml.sax.saxutils import escape
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from src.services.map_generator import gerar_imagem_mapa_rota

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
        # Vale-Transporte
        lin_headers = ["Linha / Modal", "Tarifa Un.", "Qtd/Dia", "Subtotal Diário"]
        tabela_vt_data = [
            ["Endereço Origem", dados_calculo.get('origem', 'N/A'), "", ""],
            ["Endereço Destino", dados_calculo.get('destino', 'N/A'), "", ""],
            lin_headers
        ]

        resumo_trajeto = dados_calculo.get("resumo_trajeto")
        if resumo_trajeto:
            story.append(Paragraph("Resumo do trajeto", heading_style))
            story.append(Paragraph(escape(resumo_trajeto), styles['Normal']))
            story.append(Spacer(1, 6))
        
        for det in dados_calculo.get('detalhes', []):
            tabela_vt_data.append([
                det.get('linha', 'N/A'),
                f"R$ {det.get('valor_unitario', 0):.2f}",
                str(det.get('quantidade_dia', 2)),
                f"R$ {det.get('subtotal', 0):.2f}"
            ])
            
        tabela_vt_data.append(["TOTAL DIÁRIO", "", "", f"R$ {dados_calculo.get('custo_diario', 0):.2f}"])
        tabela_vt_data.append(["ESTIMATIVA MENSAL (22 dias)", "", "", f"R$ {dados_calculo.get('custo_mensal', 0):.2f}"])

        tabela_vt = Table(tabela_vt_data, colWidths=[220, 100, 80, 140])
        tabela_vt.setStyle(TableStyle([
            ('SPAN', (1,0), (3,0)),
            ('SPAN', (1,1), (3,1)),
            ('BACKGROUND', (0,2), (-1,2), colors.HexColor('#1E3A8A')),
            ('TEXTCOLOR', (0,2), (-1,2), colors.whitesmoke),
            ('FONTNAME', (0,2), (-1,2), 'Helvetica-Bold'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#CBD5E1')),
            ('BACKGROUND', (0,-2), (-1,-1), colors.HexColor('#F1F5F9')),
            ('FONTNAME', (0,-2), (-1,-1), 'Helvetica-Bold'),
            ('PADDING', (0,0), (-1,-1), 5),
        ]))
        story.append(tabela_vt)

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
        img_buffer = gerar_imagem_mapa_rota(lat_o, lon_o, lat_d, lon_d)
        story.append(Image(img_buffer, width=540, height=270))
    else:
        story.append(Paragraph("<i>Evidência cartográfica indisponível para esta consulta.</i>", styles['Normal']))

    # Constrói o PDF
    doc.build(story)
    buffer.seek(0)
    return buffer
