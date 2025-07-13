from docx import Document
from pyzotero import zotero
from collections import defaultdict
from docx.shared import Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH
import re
from transliterate import translit

# --- настройки пользователя ---
API_KEY = 'Your_Secret_API_KEY'
USER_ID = '123456789'
LIBRARY_TYPE = 'user' # или 'group', исходя из политик Zotero
COLLECTION_NAME = 'PhD' # укажите название целевой коллекции Zotero
DOCX_PATH = '/path/to/your/work.docx'
FONT_NAME = 'Times New Roman'

# --- порядок категорий и заголовки ---
category_headers = {
    'note: normative': 'Нормативные и официальные источники',
    'note: dissertation': 'Диссертации и авторефераты',
    'note: academic': 'Научная и учебная литература, статьи из журналов и сборников',
    'note: web': 'Интернет-ресурсы',
    'note: other': 'ПРОЧИЕ ИСТОЧНИКИ'
}
category_order = list(category_headers.keys())

# --- подключение к Zotero ---
zot = zotero.Zotero(USER_ID, LIBRARY_TYPE, API_KEY)
collections = zot.collections()
collection_id = next((c['data']['key'] for c in collections if c['data']['name'] == COLLECTION_NAME), None)
if not collection_id:
    raise RuntimeError(f"Коллекция '{COLLECTION_NAME}' не найдена")

items = zot.collection_items(collection_id, limit=1000)

# --- сопоставление title -> категория ---
def normalize(text, truncate=True):
    # Приводим к нижнему регистру и убираем пробелы по краям
    text = text.strip().lower()
    # Заменяем все небуквенно-цифровые символы на пробелы для унификации
    text = re.sub(r'[^a-z0-9\sа-яё]', ' ', text)
    # Заменяем множественные пробелы на один
    text = re.sub(r'\s+', ' ', text).strip()
    if truncate:
        return text[:50]
    return text

title_category_map = {}
for item in items:
    title = item['data'].get('title', '')
    if not title:
        continue
    extra = item['data'].get('extra', '').lower()
    category = next((c for c in category_order if c in extra), 'note: other')
    # Отключаем обрезку заголовков для более точного сопоставления
    title_category_map[normalize(title, truncate=False)] = category

# --- открыть docx ---
doc = Document(DOCX_PATH)
start_index = None
for i, p in enumerate(doc.paragraphs):
    if "СПИСОК ЛИТЕРАТУРЫ" in p.text.upper():
        start_index = i + 1
        break
if start_index is None:
    raise RuntimeError("Не найден заголовок 'СПИСОК ЛИТЕРАТУРЫ'")

# --- извлечение записей ---
entries = []
for p in doc.paragraphs[start_index:]:
    if p.text.strip():
        entries.append(p.text.strip())

# --- очистка старых параграфов ---
# Удаляем все параграфы после "СПИСОК ЛИТЕРАТУРЫ", чтобы убрать пустые строки
# Идем в обратном порядке, чтобы не нарушать индексы при удалении
for i in range(len(doc.paragraphs) - 1, start_index - 1, -1):
    p = doc.paragraphs[i]
    p_element = p._element
    if p_element.getparent() is not None:
        p_element.getparent().remove(p_element)

# --- классификация ---
grouped = defaultdict(list)
pattern = re.compile(r"^\d+[\.\)]\s*(.*)")

for entry in entries:
    match = pattern.match(entry)
    text_only = match.group(1) if match else entry
    # Нормализуем текст из документа без усечения
    norm_key = normalize(text_only, truncate=False)
    # Ищем, содержится ли заголовок из Zotero в записи из документа.
    # Это делает сопоставление более гибким.
    matched = next((cat for t, cat in title_category_map.items() if t in norm_key), 'note: other')
    grouped[matched].append(text_only)


# --- добавление новых параграфов с сортировкой и стилем ---
from docx.oxml.ns import qn

def is_predominantly_russian(text):
    cyrillic_count = 0
    latin_count = 0
    for char in text:
        char_lower = char.lower()
        if 'a' <= char_lower <= 'z':
            latin_count += 1
        elif 'а' <= char_lower <= 'я' or char_lower == 'ё':
            cyrillic_count += 1
    return cyrillic_count > latin_count

def sort_key(text):
    cleaned_text = text.strip()
    if not cleaned_text:
        return (3, "")

    if is_predominantly_russian(cleaned_text):
        # Группа 1 для кириллицы, сортировка по транслиту в алфавитном порядке
        return (1, translit(cleaned_text, 'ru', reversed=False).lower())
    else:
        # Группа 2 для латиницы, сортировка по нижнему регистру
        return (2, cleaned_text.lower())

idx = 1
first_category_written = False
for cat in category_order:
    group = grouped.get(cat, [])
    if not group:
        continue

    sorted_group = sorted(group, key=sort_key)

    # Добавляем пустую строку перед заголовком, кроме самого первого
    if first_category_written:
        doc.add_paragraph()

    # заголовок группы
    header_par = doc.add_paragraph()
    first_category_written = True
    header_par.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = header_par.add_run(category_headers[cat])
    run.italic = True
    run.font.name = FONT_NAME
    run._element.rPr.rFonts.set(qn('w:eastAsia'), FONT_NAME)
    run.font.size = Pt(14)
    header_par.paragraph_format.line_spacing = 1.5

    # записи с нумерацией
    for item in sorted_group:
        para = doc.add_paragraph()
        run = para.add_run(f"{idx}. {item}")
        run.font.name = FONT_NAME
        run._element.rPr.rFonts.set(qn('w:eastAsia'), FONT_NAME)
        run.font.size = Pt(14)
        para.paragraph_format.line_spacing = 1.5
        idx += 1

# --- сохранить ---
output_path = DOCX_PATH.replace('.docx', '_sorted.docx')
doc.save(output_path)
print(f"Сохранено: {output_path}")
