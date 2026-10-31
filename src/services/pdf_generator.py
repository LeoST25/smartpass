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

    story.append(Spacer(1, 10))

    # 4. Evidência Cartográfica do Trajeto (Substitui Termos de Assinatura)
    story.append(Paragraph("3. Evidência Cartográfica Auditável", heading_style))
    
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
