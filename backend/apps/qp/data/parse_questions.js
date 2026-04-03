const fs = require('fs');
const path = require('path');

// Paths
const INPUT_FILE = path.join(__dirname, 'raw', 'response2.json');
const OUTPUT_DIR = path.join(__dirname, 'parsed');
const OUTPUT_FILE = path.join(OUTPUT_DIR, 'questions_english.json');

// Ensure output directory exists
if (!fs.existsSync(OUTPUT_DIR)) {
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });
  console.log(`Created output directory: ${OUTPUT_DIR}`);
}

// Load and parse the input file
console.log(`Reading file: ${INPUT_FILE}`);
const raw = fs.readFileSync(INPUT_FILE, 'utf8');
console.log(`File size: ${(raw.length / 1024).toFixed(1)} KB`);

const rootData = JSON.parse(raw);
console.log(`Parsed JSON successfully. Top-level type: ${rootData.type}`);
console.log(`Number of nodes: ${rootData.nodes ? rootData.nodes.length : 'N/A'}`);

// --- Helpers ---

function stripHtml(html) {
  if (typeof html !== 'string') return '';
  // Decode common HTML entities
  let text = html
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&#(\d+);/g, (_, code) => String.fromCharCode(parseInt(code, 10)))
    .replace(/&#x([0-9a-fA-F]+);/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
  // Strip HTML tags
  text = text.replace(/<[^>]*>/g, ' ');
  // Collapse whitespace
  text = text.replace(/\s+/g, ' ').trim();
  return text;
}

function hasDevanagari(text) {
  return /[\u0900-\u097F]/.test(text);
}

function extractExamType(title) {
  if (!title) return '';
  const types = ['JEE Advanced', 'JEE Main', 'MHT CET', 'BITSAT', 'AIEEE'];
  for (const t of types) {
    if (title.includes(t)) return t;
  }
  return '';
}

function extractShift(title) {
  if (!title) return '';
  const shifts = ['Morning Shift', 'Evening Shift', 'Morning Slot', 'Evening Slot', 'Offline'];
  for (const s of shifts) {
    if (title.includes(s)) return s;
  }
  return '';
}

// --- Find the paper node (node 2) ---
// It's the node whose uses.params contains "paper"
let paperNode = null;
for (const node of rootData.nodes) {
  if (
    node.uses &&
    Array.isArray(node.uses.params) &&
    node.uses.params.includes('paper')
  ) {
    paperNode = node;
    break;
  }
}

if (!paperNode) {
  console.error('ERROR: Could not find the paper node (node with uses.params containing "paper")');
  process.exit(1);
}

console.log(`Found paper node. Data array length: ${paperNode.data.length}`);

const data = paperNode.data;

// --- Resolve top-level schema ---
const topSchema = data[0];
if (!topSchema || typeof topSchema !== 'object') {
  console.error('ERROR: data[0] is not a schema object');
  process.exit(1);
}

console.log('Top-level schema keys:', Object.keys(topSchema).join(', '));

// --- Paper metadata ---
const paperSchemaIdx = topSchema.paper;
const paperSchema = data[paperSchemaIdx];
if (!paperSchema || typeof paperSchema !== 'object') {
  console.error(`ERROR: data[${paperSchemaIdx}] (paper schema) is not an object`);
  process.exit(1);
}

console.log('Paper schema keys:', Object.keys(paperSchema).join(', '));

const paperTitle = typeof paperSchema.title === 'number' ? data[paperSchema.title] : null;
const paperDate  = typeof paperSchema.date  === 'number' ? data[paperSchema.date]  : null;
const paperYear  = typeof paperSchema.year  === 'number' ? data[paperSchema.year]  : null;

console.log(`Paper title : ${paperTitle}`);
console.log(`Paper date  : ${paperDate}`);
console.log(`Paper year  : ${paperYear}`);

const examType = extractExamType(paperTitle || '');
const shift    = extractShift(paperTitle || '');

console.log(`Exam type   : ${examType}`);
console.log(`Shift       : ${shift}`);

// --- Questions ---
const questionsIdx = topSchema.questions;
const sectionsArray = data[questionsIdx];

if (!Array.isArray(sectionsArray)) {
  console.error(`ERROR: data[${questionsIdx}] (questions/sections) is not an array`);
  process.exit(1);
}

console.log(`Number of subject sections: ${sectionsArray.length}`);

const results = [];
let totalFound = 0;
let filteredOut = 0;

for (const sectionRef of sectionsArray) {
  // sectionRef is an index into data pointing to the section schema
  let sectionSchema;
  if (typeof sectionRef === 'number') {
    sectionSchema = data[sectionRef];
  } else if (typeof sectionRef === 'object' && sectionRef !== null) {
    sectionSchema = sectionRef;
  } else {
    console.warn(`  Skipping unexpected section ref type: ${typeof sectionRef}`);
    continue;
  }

  if (!sectionSchema || typeof sectionSchema !== 'object') {
    console.warn(`  Skipping invalid section schema at ref ${sectionRef}`);
    continue;
  }

  // Get subject title
  const subjectTitleIdx = sectionSchema.title;
  const subject = typeof subjectTitleIdx === 'number' ? data[subjectTitleIdx] : subjectTitleIdx;

  // Get questions list for this section
  const sectionQuestionsIdx = sectionSchema.questions;
  let sectionQuestions;
  if (typeof sectionQuestionsIdx === 'number') {
    sectionQuestions = data[sectionQuestionsIdx];
  } else if (Array.isArray(sectionQuestionsIdx)) {
    sectionQuestions = sectionQuestionsIdx;
  } else {
    console.warn(`  Section "${subject}": questions field is unexpected type`);
    continue;
  }

  if (!Array.isArray(sectionQuestions)) {
    console.warn(`  Section "${subject}": resolved questions is not an array`);
    continue;
  }

  console.log(`  Section "${subject}": ${sectionQuestions.length} questions`);

  for (const qRef of sectionQuestions) {
    // qRef is an index into data pointing to the question schema
    let qSchema;
    if (typeof qRef === 'number') {
      qSchema = data[qRef];
    } else if (typeof qRef === 'object' && qRef !== null) {
      qSchema = qRef;
    } else {
      continue;
    }

    if (!qSchema || typeof qSchema !== 'object') continue;

    // Resolve question_id
    const qIdIdx = qSchema.question_id;
    let questionId;
    if (typeof qIdIdx === 'number') {
      questionId = data[qIdIdx];
    } else {
      questionId = qIdIdx;
    }

    // Resolve content
    const contentIdx = qSchema.content;
    let contentHtml;
    if (typeof contentIdx === 'number') {
      contentHtml = data[contentIdx];
    } else {
      contentHtml = contentIdx;
    }

    if (!questionId || !contentHtml) continue;

    totalFound++;

    const plainText = stripHtml(String(contentHtml));

    // Filter: skip if contains Devanagari
    if (hasDevanagari(plainText) || hasDevanagari(String(contentHtml))) {
      filteredOut++;
      continue;
    }

    results.push({
      question_id: String(questionId),
      question: plainText,
      exam_type: examType,
      paper_title: paperTitle || '',
      exam_date: paperDate || '',
      year: paperYear || null,
      shift: shift,
      subject: String(subject || ''),
    });
  }
}

// --- Write output ---
fs.writeFileSync(OUTPUT_FILE, JSON.stringify(results, null, 2), 'utf8');

console.log('\n========== SUMMARY ==========');
console.log(`Total questions found    : ${totalFound}`);
console.log(`Filtered out (non-English): ${filteredOut}`);
console.log(`Questions saved          : ${results.length}`);
console.log(`Output file              : ${OUTPUT_FILE}`);
console.log('==============================');
