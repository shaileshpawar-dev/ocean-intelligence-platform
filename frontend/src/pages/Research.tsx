/**
 * RAG Research.
 *
 * The critical behaviour: when the backend returns `no_evidence`, this page
 * renders a refusal, not an answer. There is no code path that displays
 * generated text without retrieved sources behind it.
 */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { BookOpen, ExternalLink, Search, ShieldOff, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import type { ResearchAnswer } from "@/lib/types";
import {
  ErrorState,
  EvidenceBadge,
  LoadingSkeleton,
  PageHeader,
  SectionCard,
} from "@/components/ui";

const SUGGESTIONS = [
  "What rules govern oil discharge from ships?",
  "Which convention covers the Persian Gulf?",
  "What are the look-alikes for oil in SAR imagery?",
  "How is the risk score renormalised?",
  "What does MARPOL Annex V say about plastics?",
];

function NoEvidence({ answer }: { answer: ResearchAnswer }) {
  return (
    <div className="no-evidence">
      <span className="no-evidence-icon">
        <ShieldOff size={22} />
      </span>
      <h3>No verified evidence found</h3>
      <p>
        OceanAI could not answer this question from its verified knowledge
        corpus. <strong>No unsupported answer was generated.</strong>
      </p>
      <p className="muted-note">{answer.answer}</p>
      {answer.notes.map((note, index) => (
        <p className="muted-note" key={index}>
          {note}
        </p>
      ))}
    </div>
  );
}

export default function Research() {
  const [question, setQuestion] = useState("");
  const [docType, setDocType] = useState<string>("ALL");

  const corpus = useQuery({ queryKey: ["corpus"], queryFn: api.corpus });

  const ask = useMutation({
    mutationFn: (value: string) =>
      api.research(value, 5, docType === "ALL" ? null : docType),
  });

  const submit = (value: string) => {
    const trimmed = value.trim();
    if (trimmed.length < 3) return;
    setQuestion(trimmed);
    ask.mutate(trimmed);
  };

  const answer = ask.data;

  return (
    <>
      <PageHeader
        title="AI Research"
        subtitle="Grounded retrieval over marine-pollution instruments and platform methodology. The assistant answers only from retrieved sources."
      />

      <SectionCard>
        <form
          className="ask-form"
          onSubmit={(event) => {
            event.preventDefault();
            submit(question);
          }}
        >
          <label className="ask-label" htmlFor="research-q">
            Ask OceanAI
          </label>
          <div className="ask-row">
            <span className="ask-icon">
              <Search size={16} />
            </span>
            <input
              id="research-q"
              className="ask-input"
              placeholder="Enter an environmental research question…"
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              minLength={3}
              maxLength={500}
            />
            <select
              className="select"
              value={docType}
              onChange={(event) => setDocType(event.target.value)}
              aria-label="Source type"
            >
              <option value="ALL">All sources</option>
              <option value="regulation">Regulations</option>
              <option value="reference">Methodology</option>
            </select>
            <button
              className="btn btn-primary"
              type="submit"
              disabled={ask.isPending || question.trim().length < 3}
            >
              {ask.isPending ? "Searching…" : "Research"}
            </button>
          </div>
        </form>

        <div className="suggestions">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              className="chip"
              onClick={() => submit(suggestion)}
              type="button"
            >
              {suggestion}
            </button>
          ))}
        </div>
      </SectionCard>

      {ask.isPending && <LoadingSkeleton rows={3} height={70} />}
      {ask.isError && <ErrorState error={ask.error} />}

      {answer && (
        <>
          {answer.status === "no_evidence" ? (
            <SectionCard>
              <NoEvidence answer={answer} />
            </SectionCard>
          ) : (
            <SectionCard
              title="Answer"
              actions={
                <div className="badge-row">
                  <EvidenceBadge level="RETRIEVED" detail={`${answer.source_count} sources`} />
                  <span className="tag tone-neutral">
                    {answer.status === "grounded" ? (
                      <>
                        <Sparkles size={11} /> {answer.llm_provider}
                        {answer.llm_model ? ` · ${answer.llm_model}` : ""}
                      </>
                    ) : (
                      "retrieval only · no LLM configured"
                    )}
                  </span>
                </div>
              }
            >
              <pre className="answer-body">{answer.answer}</pre>
              {answer.notes.map((note, index) => (
                <p className="answer-note" key={index}>
                  {note}
                </p>
              ))}
            </SectionCard>
          )}

          {answer.sources.length > 0 && (
            <SectionCard
              title={`Retrieved sources (${answer.sources.length})`}
              description="Every claim above should cite one of these by its bracketed number."
            >
              <div className="source-grid">
                {answer.sources.map((source) => (
                  <article className="source-card" key={source.position}>
                    <header>
                      <span className="source-pos">[{source.position}]</span>
                      <span className={`tag tone-${source.doc_type === "regulation" ? "info" : "neutral"}`}>
                        {source.doc_type}
                      </span>
                      <span className="source-rel">
                        relevance {source.relevance.toFixed(2)}
                      </span>
                    </header>
                    <h4>{source.title}</h4>
                    <p className="source-meta">
                      {source.publication}
                      {source.year ? ` · ${source.year}` : ""}
                    </p>
                    <p className="source-excerpt">{source.excerpt}</p>
                    {source.matched_terms.length > 0 && (
                      <p className="source-terms">
                        matched: {source.matched_terms.join(", ")}
                      </p>
                    )}
                    {source.notice && (
                      <p className="source-notice">{source.notice}</p>
                    )}
                    {source.source_url && (
                      <a
                        className="source-link"
                        href={source.source_url}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        Official source <ExternalLink size={11} />
                      </a>
                    )}
                  </article>
                ))}
              </div>
            </SectionCard>
          )}
        </>
      )}

      <SectionCard
        title="Knowledge corpus"
        description="What the assistant can actually draw on — and what it cannot."
        actions={<BookOpen size={15} className="text-muted" />}
      >
        {corpus.isLoading ? (
          <LoadingSkeleton rows={2} height={40} />
        ) : corpus.isError ? (
          <ErrorState error={corpus.error} />
        ) : corpus.data ? (
          <>
            <div className="corpus-stats">
              <div>
                <strong>{corpus.data.documents}</strong>
                <span>documents</span>
              </div>
              <div>
                <strong>{corpus.data.chunks}</strong>
                <span>retrievable passages</span>
              </div>
              {Object.entries(corpus.data.by_type).map(([type, count]) => (
                <div key={type}>
                  <strong>{count}</strong>
                  <span>{type}</span>
                </div>
              ))}
            </div>
            <div className="kv">
              <span>Retriever</span>
              <span className="mono">{corpus.data.retriever}</span>
            </div>
            <div className="kv">
              <span>Reranker</span>
              <span className="mono">{corpus.data.reranker}</span>
            </div>
            <ul className="caveat-list tight">
              {corpus.data.notes.map((note, index) => (
                <li key={index}>{note}</li>
              ))}
            </ul>
          </>
        ) : null}
      </SectionCard>
    </>
  );
}
