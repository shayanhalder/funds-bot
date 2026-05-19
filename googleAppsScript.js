// Configuration

const scriptProperties = PropertiesService.getScriptProperties();
const SPREADSHEET_ID = scriptProperties.getProperty("SPREADSHEET_ID");
const SHEET_NAME = scriptProperties.getProperty("SHEET_NAME");

const PICKLEBALL_KEYWORDS = [
  "pickleball", "pickle", "pball", "tryouts", "competition", "comp",
  "tournament", "tourney", "reimbursement", "classic", "doubles",
  "mixed", "uci", "uc irvine", "anteater", "stole", 
];

// Regex patterns
// "[First Last] paid you $25.00" -> Income
const RE_PAID_YOU = /^(.+?)\s+paid you\s+\$([\d,]+(?:\.\d{2})?)\s*$/i;
// "You paid [First Last] $25.00" -> Expense
const RE_YOU_PAID = /^You paid\s+(.+?)\s+\$([\d,]+(?:\.\d{2})?)\s*$/i;

function processEmails() {
  // 1. Get unread threads up to 5 minutes ago
  const fiveMinutesAgo = Math.floor((new Date().getTime() - (5 * 60 * 1000)) / 1000);
  
  // Note: 'after' uses seconds since epoch in Gmail search
  const searchQuery = `from:venmo@venmo.com is:unread after:${fiveMinutesAgo}`;
  const threads = GmailApp.search(searchQuery);
  const emailBatch = [];

  for (const thread of threads) {
    const messages = thread.getMessages();
    // Get the last message in the thread
    const lastMessage = messages[messages.length - 1];
    const messageDate = lastMessage.getDate();

    // Store in same format as Python expected
    emailBatch.push({
      "id": lastMessage.getId(),
      "threadId": thread.getId(),
      "subject": lastMessage.getSubject(),
      "from": lastMessage.getFrom(),
      "date": messageDate,
      "body": lastMessage.getPlainBody(),
      "link": thread.getPermalink()
    });

    lastMessage.markRead(); 
  }
  
  if (emailBatch.length === 0) {
    console.log("No new emails to process.");
    return;
  }

  const result = updateSpreadsheet(emailBatch);
  console.log("Processing result:", JSON.stringify(result));
}

function updateSpreadsheet(emails) {
  const added = [];
  const skipped = [];
  
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  
  if (!sheet) {
    throw new Error(`Sheet "${SHEET_NAME}" not found in spreadsheet "${SPREADSHEET_ID}"`);
  }

  for (const email of emails) {
    const emailId = email.id || "?";
    const fromHeader = email.from || "";
    const subject = email.subject || "";
    const body = email.body || "";
    const date = email.date; 
    
    console.log(`Processing Email: subject="${subject}"`);

    if (!isFromVenmo(fromHeader)) {
      skipped.push({ "id": emailId, "reason": "not_from_venmo" });
      continue;
    }

    if (!isPickleballRelated(body)) {
      skipped.push({ "id": emailId, "reason": "not_pickleball_related" });
      continue;
    }

    const parsed = parseVenmoSubject(subject);
    if (!parsed) {
      skipped.push({ "id": emailId, "reason": "could_not_parse_subject" });
      continue;
    }

    const { person, amount, category } = parsed;
    const dateStr = formatDate(date);
    
    const notesMatch = body.match(/\n00\n\n([\s\S]*?)\n\nSee transaction \n/);
    const notes = notesMatch ? notesMatch[1].trim() : "";
    const account = "Venmo";

    const success = addTransaction(sheet, dateStr, category, amount, notes, person, account);
    
    if (success) {
      added.push({
        "id": emailId,
        "person": person,
        "amount": amount,
        "category": category
      });
    } else {
      skipped.push({ "id": emailId, "reason": "add_transaction_failed" });
    }
  }

  return {
    "processed": emails.length,
    "added": added.length,
    "skipped": skipped.length,
    "added_details": added,
    "skipped_details": skipped
  };
}

/**
 * Equivalent to _is_from_venmo
 */
function isFromVenmo(fromHeader) {
  if (!fromHeader) return false;
  return fromHeader.toLowerCase().includes("venmo");
}

/**
 * Equivalent to _is_pickleball_related
 */
function isPickleballRelated(body) {
  if (!body) return false;
  const formattedBody = body.toLowerCase().split(/[" "\n]/);
  return PICKLEBALL_KEYWORDS.some(kw => formattedBody.includes(kw.toLowerCase()));
}

/**
 * Equivalent to _parse_venmo_subject
 */
function parseVenmoSubject(subject) {
  if (!subject || !subject.trim()) return null;
  subject = subject.trim();

  // Someone paid you
  let m = subject.match(RE_PAID_YOU);
  if (m) {
    const person = m[1].trim();
    const amountStr = m[2].replace(/,/g, "");
    const amount = parseFloat(amountStr);
    if (!isNaN(amount)) {
      return { person, amount, category: "Income" };
    }
  }

  // You paid someone
  m = subject.match(RE_YOU_PAID);
  if (m) {
    const person = m[1].trim();
    const amountStr = m[2].replace(/,/g, "");
    let amount = parseFloat(amountStr);
    if (!isNaN(amount)) {
      amount = -1 * amount;
      return { person, amount, category: "Expense" };
    }
  }

  return null;
}

/**
 * Equivalent to _format_date
 */
function formatDate(dateInput) {
  if (!dateInput) return Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd");
  
  let dt;
  if (typeof dateInput === 'string') {
    dt = new Date(dateInput);
  } else if (dateInput instanceof Date) {
    dt = dateInput;
  } else {
    dt = new Date();
  }
  
  // Use GAS utility to format date
  // Session.getScriptTimeZone() ensures we use the script's timezone, 
  // or use "GMT" if strict UTC is needed like the Python code's utcnow() fallback.
  // Python code used datetime.utcnow().strftime("%Y-%m-%d") as fallback.
  return Utilities.formatDate(dt, Session.getScriptTimeZone(), "yyyy-MM-dd");
}

/**
 * Equivalent to actions.add_transaction
 * Inserts a row at index 8 (row 8 in 1-based index)
 */
function addTransaction(sheet, date, category, amount, notes, person, account) {
  const validCategories = ["Income", "Expense", "Account Transfer"];
  if (!validCategories.includes(category)) {
    console.error(`Category must be one of ${validCategories.join(", ")}`);
    return false;
  }

  try {
    // Insert a blank row at row 8 (shifting existing rows down)
    // Python code: startIndex: 7, endIndex: 8 (0-based) -> Row 8 (1-based)
    sheet.insertRowBefore(8);
    
    // Set values for the new row
    // Columns: A=Date, B=Category, C=Amount, D=Notes, E=Person, F=Account
    const values = [[date, category, amount, notes, person, account]];
    
    // getRange(row, column, numRows, numColumns)
    sheet.getRange(8, 1, 1, 6).setValues(values);
    
    console.log(`Transaction added successfully: ${person}, ${amount}`);
    return true;
  } catch (e) {
    console.error(`Error adding transaction: ${e.toString()}`);
    return false;
  }
}
