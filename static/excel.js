const MIME_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"];
const DAY_TYPE_NAMES = {
  NORMAL: "一般日",
  BIG: "大日",
  OFF: "停爐",
  CUSTOM: "其他",
};

function escapeXml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&apos;");
}

function columnName(index) {
  let current = index;
  let name = "";
  while (current > 0) {
    current -= 1;
    name = String.fromCharCode(65 + (current % 26)) + name;
    current = Math.floor(current / 26);
  }
  return name;
}

function cellXml(row, column, value, style = 11) {
  const reference = `${columnName(column)}${row}`;
  const styleAttribute = style ? ` s="${style}"` : "";
  if (typeof value === "number" && Number.isFinite(value)) {
    return `<c r="${reference}"${styleAttribute}><v>${value}</v></c>`;
  }
  return `<c r="${reference}" t="inlineStr"${styleAttribute}><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;
}

function rowXml(rowNumber, values, styles = []) {
  const cells = values.map((value, index) => cellXml(rowNumber, index + 1, value, styles[index] ?? 11));
  return `<row r="${rowNumber}">${cells.join("")}</row>`;
}

function columnsXml(widths) {
  const columns = widths.map((width, index) => (
    `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`
  ));
  return `<cols>${columns.join("")}</cols>`;
}

function worksheetXml({ rows, widths, lastColumn, lastRow, freeze, autoFilter }) {
  const pane = freeze
    ? `<pane ${freeze.x ? `xSplit="${freeze.x}" ` : ""}${freeze.y ? `ySplit="${freeze.y}" ` : ""}topLeftCell="${freeze.cell}" activePane="bottomRight" state="frozen"/>`
    : "";
  const filter = autoFilter ? `<autoFilter ref="${autoFilter}"/>` : "";
  return `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:${lastColumn}${lastRow}"/>
  <sheetViews><sheetView workbookViewId="0">${pane}</sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="19"/>
  ${columnsXml(widths)}
  <sheetData>${rows.join("")}</sheetData>
  ${filter}
</worksheet>`;
}

function scheduleSheet(result, config) {
  const headers = ["日期", "週", "類型", "標記", "需求", ...config.employees];
  const rows = [rowXml(1, headers, headers.map(() => 1))];
  const rowStyles = { NORMAL: 11, BIG: 2, OFF: 3, CUSTOM: 4 };
  const roleStyles = { A: 5, B: 6, C: 7, 休假: 8, 未排: 9, 停爐: 3 };

  result.schedule.forEach((day, index) => {
    const requirements = day.requirements;
    const requirementText = ["A", "B", "C"].map((role) => `${role}${requirements[role]}`).join(" / ");
    const values = [
      day.date,
      `週${WEEKDAY_NAMES[day.weekday]}`,
      DAY_TYPE_NAMES[day.day_type],
      day.label || "",
      requirementText,
    ];
    const styles = Array(5).fill(rowStyles[day.day_type] ?? 11);
    const vacationNames = new Set(day.vacations || []);
    config.employees.forEach((name) => {
      let value;
      if (day.day_type === "OFF") value = "停爐";
      else if (vacationNames.has(name)) value = "休假";
      else value = day.assignment?.[name] || "未排";
      values.push(value);
      styles.push(roleStyles[value] ?? 11);
    });
    rows.push(rowXml(index + 2, values, styles));
  });

  const lastColumn = columnName(headers.length);
  return worksheetXml({
    rows,
    widths: [13, 6, 9, 16, 18, ...config.employees.map(() => 8)],
    lastColumn,
    lastRow: result.schedule.length + 1,
    freeze: { x: 5, y: 1, cell: "F2" },
    autoFilter: `A1:${lastColumn}${result.schedule.length + 1}`,
  });
}

function statsSheet(result) {
  const headers = [
    "人員", "休假", "可排", "實排", "未排", "A", "B", "C",
    "A比例", "B比例", "C比例", "連B次數", "最長連B", "期末連B",
  ];
  const rows = [
    rowXml(1, ["整體均衡分數", result.stats.balance.overall_score, "滿分 100；依每人可排天數與允許角色比較"], [1, 11, 11]),
    rowXml(3, headers, headers.map(() => 1)),
  ];

  result.stats.employees.forEach((stat, index) => {
    const values = [
      stat.name,
      stat.vacation_days,
      stat.available_days,
      stat.assigned_days,
      stat.unassigned_days,
      stat.role_counts.A,
      stat.role_counts.B,
      stat.role_counts.C,
      stat.role_percentages.A,
      stat.role_percentages.B,
      stat.role_percentages.C,
      stat.consecutive_b_occurrences,
      stat.longest_b_streak,
      stat.ending_b_streak,
    ];
    const styles = values.map((_, column) => (column >= 8 && column <= 10 ? 10 : 11));
    rows.push(rowXml(index + 4, values, styles));
  });

  return worksheetXml({
    rows,
    widths: headers.map((_, index) => (index === 0 ? 13 : 10)),
    lastColumn: columnName(headers.length),
    lastRow: result.stats.employees.length + 3,
    freeze: { x: 0, y: 3, cell: "A4" },
  });
}

function vacationSheet(vacations, config) {
  const headers = ["人員", "休假天數", "休假日期"];
  const rows = [rowXml(1, headers, headers.map(() => 1))];
  config.employees.forEach((name, index) => {
    const dates = [...(vacations[name] || [])].sort();
    rows.push(rowXml(index + 2, [name, dates.length, dates.join("、")], [11, 11, 11]));
  });
  return worksheetXml({
    rows,
    widths: [12, 12, 80],
    lastColumn: "C",
    lastRow: config.employees.length + 1,
    freeze: { x: 0, y: 1, cell: "A2" },
  });
}

const STYLES_XML = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="2">
    <font><sz val="11"/><name val="Calibri"/><family val="2"/></font>
    <font><b/><color rgb="FF24323D"/><sz val="11"/><name val="Calibri"/><family val="2"/></font>
  </fonts>
  <fills count="11">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFDCEAE6"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFFFF0D8"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFE8EBED"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFECE6F7"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF9D976"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFCFE4F7"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFCEE9D5"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF5D6D6"/><bgColor indexed="64"/></patternFill></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FFF1F1F1"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="12">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="3" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="4" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="5" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="6" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="7" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="8" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="9" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="10" borderId="0" xfId="0" applyFill="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="10" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>`;

function workbookFiles(result, vacations, config) {
  const contentTypes = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet3.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>`;
  const rootRelationships = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>`;
  const workbook = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <bookViews><workbookView/></bookViews>
  <sheets>
    <sheet name="每日班表" sheetId="1" r:id="rId1"/>
    <sheet name="人員統計" sheetId="2" r:id="rId2"/>
    <sheet name="休假設定" sheetId="3" r:id="rId3"/>
  </sheets>
</workbook>`;
  const workbookRelationships = `<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet3.xml"/>
  <Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>`;

  return [
    ["[Content_Types].xml", contentTypes],
    ["_rels/.rels", rootRelationships],
    ["xl/workbook.xml", workbook],
    ["xl/_rels/workbook.xml.rels", workbookRelationships],
    ["xl/styles.xml", STYLES_XML],
    ["xl/worksheets/sheet1.xml", scheduleSheet(result, config)],
    ["xl/worksheets/sheet2.xml", statsSheet(result)],
    ["xl/worksheets/sheet3.xml", vacationSheet(vacations, config)],
  ];
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let number = 0; number < 256; number += 1) {
    let current = number;
    for (let bit = 0; bit < 8; bit += 1) {
      current = (current & 1) ? (0xedb88320 ^ (current >>> 1)) : (current >>> 1);
    }
    table[number] = current >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  bytes.forEach((byte) => {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  });
  return (crc ^ 0xffffffff) >>> 0;
}

function littleEndian(values) {
  const length = values.reduce((sum, item) => sum + item.bytes, 0);
  const result = new Uint8Array(length);
  const view = new DataView(result.buffer);
  let offset = 0;
  values.forEach(({ value, bytes }) => {
    if (bytes === 2) view.setUint16(offset, value, true);
    else view.setUint32(offset, value >>> 0, true);
    offset += bytes;
  });
  return result;
}

function combine(chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const output = new Uint8Array(total);
  let offset = 0;
  chunks.forEach((chunk) => {
    output.set(chunk, offset);
    offset += chunk.length;
  });
  return output;
}

function dosTimestamp(now = new Date()) {
  const year = Math.max(1980, now.getFullYear());
  const date = ((year - 1980) << 9) | ((now.getMonth() + 1) << 5) | now.getDate();
  const time = (now.getHours() << 11) | (now.getMinutes() << 5) | Math.floor(now.getSeconds() / 2);
  return { date, time };
}

function createZip(files) {
  const encoder = new TextEncoder();
  const localChunks = [];
  const centralChunks = [];
  const { date, time } = dosTimestamp();
  let localOffset = 0;

  files.forEach(([filename, text]) => {
    const name = encoder.encode(filename);
    const data = encoder.encode(text);
    const checksum = crc32(data);
    const flags = 0x0800;
    const localHeader = littleEndian([
      { value: 0x04034b50, bytes: 4 }, { value: 20, bytes: 2 }, { value: flags, bytes: 2 },
      { value: 0, bytes: 2 }, { value: time, bytes: 2 }, { value: date, bytes: 2 },
      { value: checksum, bytes: 4 }, { value: data.length, bytes: 4 }, { value: data.length, bytes: 4 },
      { value: name.length, bytes: 2 }, { value: 0, bytes: 2 },
    ]);
    localChunks.push(localHeader, name, data);

    const centralHeader = littleEndian([
      { value: 0x02014b50, bytes: 4 }, { value: 20, bytes: 2 }, { value: 20, bytes: 2 },
      { value: flags, bytes: 2 }, { value: 0, bytes: 2 }, { value: time, bytes: 2 },
      { value: date, bytes: 2 }, { value: checksum, bytes: 4 }, { value: data.length, bytes: 4 },
      { value: data.length, bytes: 4 }, { value: name.length, bytes: 2 }, { value: 0, bytes: 2 },
      { value: 0, bytes: 2 }, { value: 0, bytes: 2 }, { value: 0, bytes: 2 },
      { value: 0, bytes: 4 }, { value: localOffset, bytes: 4 },
    ]);
    centralChunks.push(centralHeader, name);
    localOffset += localHeader.length + name.length + data.length;
  });

  const centralDirectory = combine(centralChunks);
  const end = littleEndian([
    { value: 0x06054b50, bytes: 4 }, { value: 0, bytes: 2 }, { value: 0, bytes: 2 },
    { value: files.length, bytes: 2 }, { value: files.length, bytes: 2 },
    { value: centralDirectory.length, bytes: 4 }, { value: localOffset, bytes: 4 },
    { value: 0, bytes: 2 },
  ]);
  return combine([...localChunks, centralDirectory, end]);
}

export function buildScheduleWorkbookBytes(result, vacations, config) {
  return createZip(workbookFiles(result, vacations, config));
}

export function buildScheduleWorkbook(result, vacations, config) {
  return new Blob([buildScheduleWorkbookBytes(result, vacations, config)], { type: MIME_TYPE });
}

export { MIME_TYPE };
