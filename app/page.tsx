"use client";

import { useMemo, useRef, useState } from "react";
import { ArrowUpRight, FileText, LockKeyhole, Plus, Search, Shield, Upload } from "lucide-react";

type Level = "CRITICAL" | "GREY" | "UNCRITICAL";
type Finding = { id: string; value: string; category: string; level: Level; reason: string };
type Doc = { id: string; name: string; type: string; size: string; date: string; findings: Finding[] };
type Tab = "Overview" | "Documents" | "Privacy rules";

const initial: Doc[] = [{
  id: "demo-1", name: "Mandatsvertrag_Muster.pdf", type: "PDF", size: "284 KB", date: "Sample",
  findings: [
    { id: "f1", value: "Max Mustermann", category: "Person", level: "GREY", reason: "Directly identifying information" },
    { id: "f2", value: "IBAN", category: "Bank details", level: "CRITICAL", reason: "Financial information" },
    { id: "f3", value: "§ 280 BGB", category: "Legal reference", level: "UNCRITICAL", reason: "Public legal information" }
  ]
}];

export default function Home() {
  const [tab, setTab] = useState<Tab>("Overview");
  const [docs, setDocs] = useState<Doc[]>(initial);
  const [active, setActive] = useState("demo-1");
  const [search, setSearch] = useState("");
  const [text, setText] = useState("");
  const [notice, setNotice] = useState("Demo mode — files are not uploaded or processed.");
  const input = useRef<HTMLInputElement>(null);
  const doc = docs.find(d => d.id === active);
  const findings = docs.flatMap(d => d.findings);
  const counts = useMemo(() => ({
    CRITICAL: findings.filter(f => f.level === "CRITICAL").length,
    GREY: findings.filter(f => f.level === "GREY").length,
    UNCRITICAL: findings.filter(f => f.level === "UNCRITICAL").length
  }), [findings]);
  const visible = docs.filter(d => d.name.toLowerCase().includes(search.toLowerCase()));

  function addFiles(files: FileList | null) {
    if (!files?.length) return;
    const added = Array.from(files).map((f, i) => ({
      id: String(Date.now() + i), name: f.name, type: f.name.split(".").pop()?.toUpperCase() || "FILE",
      size: Math.max(1, Math.round(f.size / 1024)) + " KB", date: "Just now", findings: []
    }));
    setDocs(v => [...added, ...v]); setActive(added[0].id); setTab("Documents");
    setNotice("Filename added locally. File contents are not uploaded or processed.");
  }

  function addText() {
    if (!text.trim()) return;
    const d = { id: String(Date.now()), name: "Text note " + (docs.length + 1) + ".txt", type: "TXT", size: text.length + " chars", date: "Just now", findings: [] };
    setDocs(v => [d, ...v]); setActive(d.id); setText("");
    setNotice("Text is only stored in temporary browser state.");
  }

  return (
    <main className="cato-shell">
      <header className="cato-header">
        <a className="cato-logo"><span><Shield size={16}/></span>CATO</a>
        <nav className="top-tabs" aria-label="Main navigation">
          {(["Overview", "Documents", "Privacy rules"] as Tab[]).map(t => <button key={t} className={tab === t ? "top-tab active" : "top-tab"} onClick={() => setTab(t)}>{t}{t === "Documents" && <small>{docs.length}</small>}</button>)}
        </nav>
        <div className="environment"><i/> DEMO</div>
      </header>

      <div className="cato-content">
        <div className="page-intro">
          <div><div className="eyebrow">PRIVACY INFRASTRUCTURE FOR AI</div><h1>{tab}</h1><p>{tab === "Overview" ? "Control what your AI agents are allowed to see." : tab === "Documents" ? "Manage and inspect your source documents." : "Define how sensitive information is handled."}</p></div>
          {tab !== "Privacy rules" && <button className="primary-action" onClick={() => input.current?.click()}><Plus size={15}/> Add document</button>}
        </div>

        <div className="prototype-note"><LockKeyhole size={13}/><span><b>Prototype.</b> Detection and redaction are not yet connected to document uploads. Do not use confidential files.</span></div>

        {tab === "Overview" && <>
          <section className="overview-counts">
            <div><span>CRITICAL</span><strong>{counts.CRITICAL.toString().padStart(2, "0")}</strong><small>Never shared</small></div>
            <div><span>GREY</span><strong>{counts.GREY.toString().padStart(2, "0")}</strong><small>Requires consent</small></div>
            <div><span>UNCRITICAL</span><strong>{counts.UNCRITICAL.toString().padStart(2, "0")}</strong><small>Allowed by policy</small></div>
          </section>

          <section className="plain-section">
            <div className="section-heading"><div><h2>Recent documents</h2><p>Documents in this workspace</p></div><button className="subtle-link" onClick={() => setTab("Documents")}>View all <ArrowUpRight size={13}/></button></div>
            <div className="doc-table-head"><span>DOCUMENT</span><span>TYPE</span><span>SIZE</span><span>STATUS</span></div>
            {docs.slice(0, 5).map(d => <button className="doc-table-row" key={d.id} onClick={() => { setActive(d.id); setTab("Documents"); }}><span className="doc-title"><FileText size={15}/><b>{d.name}</b></span><span>{d.type}</span><span>{d.size}</span><span className="doc-status">{d.findings.length ? "Sample data" : "Not analysed"}</span></button>)}
            {!docs.length && <div className="empty-line">No documents yet.</div>}
          </section>

          <section className="plain-section policy-overview">
            <div className="section-heading"><div><h2>Privacy policy</h2><p>Default classification behaviour</p></div><button className="subtle-link" onClick={() => setTab("Privacy rules")}>View rules <ArrowUpRight size={13}/></button></div>
            <div className="policy-columns">
              <div><b>Critical</b><p>Never shared with an AI agent.</p></div>
              <div><b>Grey</b><p>Requires explicit, request-specific consent.</p></div>
              <div><b>Uncritical</b><p>May pass according to policy.</p></div>
            </div>
          </section>
        </>}

        {tab === "Documents" && <>
          <section className="plain-section upload-section">
            <div className="section-heading"><div><h2>Add content</h2><p>Upload a document or paste text for analysis.</p></div></div>
            <button className="minimal-drop" onClick={() => input.current?.click()} onDragOver={e => e.preventDefault()} onDrop={e => { e.preventDefault(); addFiles(e.dataTransfer.files); }}><Upload size={17}/><b>Drop files here or <u>browse</u></b><small>PDF, DOCX, TXT · max 20 MB</small></button>
            <input ref={input} hidden type="file" multiple accept=".pdf,.docx,.txt" onChange={e => addFiles(e.target.files)}/>
            <div className="paste-row"><textarea value={text} onChange={e => setText(e.target.value)} placeholder="Or paste text here…" rows={3}/><button className="primary-action" onClick={addText} disabled={!text.trim()}><Plus size={14}/> Add text</button></div>
          </section>
          <section className="plain-section">
            <div className="section-heading"><div><h2>All documents</h2><p>{docs.length} items</p></div><label className="minimal-search"><Search size={14}/><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search documents"/></label></div>
            <div className="doc-table-head"><span>DOCUMENT</span><span>TYPE</span><span>SIZE</span><span>STATUS</span></div>
            {visible.map(d => <button className={"doc-table-row " + (active === d.id ? "selected" : "")} key={d.id} onClick={() => setActive(d.id)}><span className="doc-title"><FileText size={15}/><b>{d.name}</b></span><span>{d.type}</span><span>{d.size}</span><span className="doc-status">{d.findings.length ? "Sample data" : "Not analysed"}</span></button>)}
            {!visible.length && <div className="empty-line">No documents found.</div>}
          </section>
          {doc && <section className="plain-section"><div className="section-heading"><div><h2>Privacy analysis</h2><p>{doc.name}</p></div></div>
            {doc.findings.length ? doc.findings.map(f => <div className="finding-line" key={f.id}><span className={"finding-level " + f.level.toLowerCase()}>{f.level}</span><b>{f.value}</b><small>{f.category} · {f.reason}</small></div>) : <div className="empty-line">No analysis available. The processing engine is not connected to document uploads.</div>}
          </section>}
        </>}

        {tab === "Privacy rules" && <section className="plain-section rules-list">
          <div className="section-heading"><div><h2>Classification policy</h2><p>How information is handled before reaching an AI agent.</p></div></div>
          <div className="rule-row"><div><span className="rule-marker critical"/> <b>Critical</b></div><p>Never shared. User consent cannot override this rule.</p><small>BLOCKED BY DEFAULT</small></div>
          <div className="rule-row"><div><span className="rule-marker grey"/> <b>Grey</b></div><p>Shared only after explicit, request-specific user consent.</p><small>CONSENT REQUIRED</small></div>
          <div className="rule-row"><div><span className="rule-marker uncritical"/> <b>Uncritical</b></div><p>May be shared according to the active policy.</p><small>POLICY CONTROLLED</small></div>
          <p className="rules-disclaimer">These rules are product design principles. Enforcement is not yet active for uploaded documents.</p>
        </section>}

        <footer className="cato-footer"><span>© 2026 CATO</span><span>{notice}</span><span>PRIVACY LAYER FOR AI</span></footer>
      </div>
    </main>
  );
}
