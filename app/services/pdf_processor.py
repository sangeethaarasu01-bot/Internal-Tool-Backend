# app/services/pdf_processor.py
from sqlalchemy.orm import Session
from app.models import Conversion, ConversionStatus
import os
import time
import logging
from datetime import datetime  # ← Add this import
from PyPDF2 import PdfReader
import xmltodict
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def process_pdf(conversion_id: int, file_path: str, db: Session):
    conversion = db.query(Conversion).filter(Conversion.id == conversion_id).first()
    
    try:
        # Update status to processing
        if conversion:
            conversion.status = ConversionStatus.PROCESSING
            db.commit()
        
        logger.info(f"Processing PDF: {file_path}")
        
        # Read PDF
        with open(file_path, 'rb') as file:
            pdf_reader = PdfReader(file)
            num_pages = len(pdf_reader.pages)
            logger.info(f"PDF has {num_pages} pages")
            
            # Extract text
            text_content = ""
            for page in pdf_reader.pages:
                text_content += page.extract_text()
        
        # Generate XML
        xml_content = generate_ieee_xml(text_content, file_path)
        
        # Update conversion
        if conversion:
            conversion.status = ConversionStatus.SUCCESS
            conversion.xml_content = xml_content
            conversion.completed_at = datetime.now()
            db.commit()
        
        logger.info(f"Conversion {conversion_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Error processing conversion {conversion_id}: {str(e)}")
        if conversion:
            conversion.status = ConversionStatus.FAILED
            conversion.error_message = str(e)
            db.commit()

def generate_ieee_xml(text_content: str, filename: str) -> str:
    """Generate IEEE XML format from PDF content"""
    
    xml_template = f'''<?xml version="1.0" encoding="UTF-8"?>
<ieee-article>
    <header>
        <title>Converted from {os.path.basename(filename)}</title>
        <conversion-date>{datetime.now().isoformat()}</conversion-date>
    </header>
    <content>
        <![CDATA[{text_content[:1000]}]]>
    </content>
    <metadata>
        <pages>{len(text_content.split('\\n'))}</pages>
        <format>IEEE XML</format>
    </metadata>
</ieee-article>'''
    
    return xml_template