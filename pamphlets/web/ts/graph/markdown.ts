// Markdown, for a Comment box's words.
//
// Built as elements, never as HTML: a comment may have come in a .pam file
// from somebody else, and text that is only ever text cannot run anything.
// The parts people write in a note — headings, emphasis, code, links,
// lists, task lists, quotes and rules — and nothing that needs more.
//
// Part of the Configuration canvas; see main.ts.

/** Words written in Markdown, as elements to put in a box. */
function graphMarkdown(words: string): DocumentFragment {
  const out = document.createDocumentFragment();
  const lines = words.replace(/\r\n?/g, "\n").split("\n");
  let index = 0;
  while (index < lines.length) {
    const line = lines[index] ?? "";

    // A fenced block of code: kept exactly as written.
    const fence = /^\s*(```|~~~)/.exec(line);
    if (fence !== null) {
      const closing = fence[1] ?? "```";
      const kept: string[] = [];
      index += 1;
      while (index < lines.length && !(lines[index] ?? "").trim().startsWith(closing)) {
        kept.push(lines[index] ?? "");
        index += 1;
      }
      index += 1;
      const pre = document.createElement("pre");
      pre.appendChild(graphElement("code", "", kept.join("\n")));
      out.appendChild(pre);
      continue;
    }

    if (line.trim() === "") {
      index += 1;
      continue;
    }

    const heading = /^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/.exec(line);
    if (heading !== null) {
      // Kept small: a note's heading is a heading inside a box, not a page's.
      const level = Math.min(6, (heading[1] ?? "#").length + 2);
      const head = document.createElement(`h${level}`);
      graphMarkdownInline(head, heading[2] ?? "");
      out.appendChild(head);
      index += 1;
      continue;
    }

    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) {
      out.appendChild(document.createElement("hr"));
      index += 1;
      continue;
    }

    if (/^\s{0,3}>/.test(line)) {
      const quoted: string[] = [];
      while (index < lines.length && /^\s{0,3}>/.test(lines[index] ?? "")) {
        quoted.push((lines[index] ?? "").replace(/^\s{0,3}>\s?/, ""));
        index += 1;
      }
      const quote = document.createElement("blockquote");
      quote.appendChild(graphMarkdown(quoted.join("\n")));
      out.appendChild(quote);
      continue;
    }

    const bullet = /^\s*([-*+]|\d{1,9}[.)])\s+/;
    if (bullet.test(line)) {
      const ordered = /^\s*\d/.test(line);
      const list = document.createElement(ordered ? "ol" : "ul");
      const first = /^\s*(\d{1,9})/.exec(line);
      if (ordered && first !== null && first[1] !== "1") list.setAttribute("start", first[1] ?? "1");
      while (index < lines.length && bullet.test(lines[index] ?? "")) {
        let said = (lines[index] ?? "").replace(bullet, "");
        index += 1;
        // A line under an item, indented, carries on that item.
        while (index < lines.length && /^\s{2,}\S/.test(lines[index] ?? "") && !bullet.test(lines[index] ?? "")) {
          said += ` ${(lines[index] ?? "").trim()}`;
          index += 1;
        }
        const item = document.createElement("li");
        const task = /^\[([ xX])\]\s+/.exec(said);
        if (task !== null) {
          // A task: ticked or not, as written. Shown, not a switch to flip.
          item.className = "is-task";
          const box = document.createElement("input");
          box.type = "checkbox";
          box.disabled = true;
          box.checked = (task[1] ?? " ") !== " ";
          item.appendChild(box);
          said = said.slice(task[0].length);
        }
        graphMarkdownInline(item, said);
        list.appendChild(item);
      }
      out.appendChild(list);
      continue;
    }

    // A paragraph: lines until a blank one or something else begins. A line
    // break inside it is kept, as somebody writing a note means one.
    const kept: string[] = [];
    while (index < lines.length) {
      const next = lines[index] ?? "";
      if (next.trim() === "" || (kept.length > 0 && graphMarkdownStarts(next))) break;
      kept.push(next);
      index += 1;
    }
    const para = document.createElement("p");
    kept.forEach((one, at): void => {
      if (at > 0) para.appendChild(document.createElement("br"));
      graphMarkdownInline(para, one.trim());
    });
    out.appendChild(para);
  }
  return out;
}

/** Whether a line starts a block of its own, ending the paragraph before it. */
function graphMarkdownStarts(line: string): boolean {
  return /^\s{0,3}(#{1,6}\s|>|```|~~~)/.test(line)
    || /^\s*([-*+]|\d{1,9}[.)])\s+/.test(line)
    || /^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line);
}

/** Only addresses that go somewhere to read: never a script. */
function graphMarkdownHref(href: string): string | null {
  const wanted = href.trim();
  return /^(https?:\/\/|mailto:)/i.test(wanted) ? wanted : null;
}

/** The marks inside a line: code, links, bold, italic and struck-through,
 *  appended to `into` as elements and text. */
function graphMarkdownInline(into: Node, words: string): void {
  // In the order they bind: code first, since nothing inside it is a mark.
  const marks = /`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|<(https?:\/\/[^>\s]+)>|\*\*(.+?)\*\*|__(.+?)__|~~(.+?)~~|\*(?!\s)(.+?)\*|_(?!\s)(.+?)_(?!\w)/g;
  let from = 0;
  let found = marks.exec(words);
  while (found !== null) {
    const at = found.index;
    // snake_case is a word, not emphasis: an underscore inside one is kept.
    if (found[9] !== undefined && at > 0 && /\w/.test(words.charAt(at - 1))) {
      marks.lastIndex = at + 1;
      found = marks.exec(words);
      continue;
    }
    if (at > from) into.appendChild(document.createTextNode(words.slice(from, at)));
    from = at + found[0].length;
    if (found[1] !== undefined) {
      into.appendChild(graphElement("code", "", found[1]));
    } else if (found[2] !== undefined || found[4] !== undefined) {
      const href = graphMarkdownHref(found[3] ?? found[4] ?? "");
      if (href === null) {
        // Not somewhere to read — a script, say: shown as it was written.
        into.appendChild(document.createTextNode(found[0]));
      } else {
        const link = document.createElement("a");
        link.href = href;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        graphMarkdownInline(link, found[2] ?? href);
        into.appendChild(link);
      }
    } else {
      const [tag, inner] = found[5] !== undefined || found[6] !== undefined
        ? ["strong", found[5] ?? found[6] ?? ""]
        : found[7] !== undefined ? ["del", found[7]] : ["em", found[8] ?? found[9] ?? ""];
      const mark = document.createElement(tag);
      graphMarkdownInline(mark, inner);
      into.appendChild(mark);
    }
    found = marks.exec(words);
  }
  if (from < words.length) into.appendChild(document.createTextNode(words.slice(from)));
}
