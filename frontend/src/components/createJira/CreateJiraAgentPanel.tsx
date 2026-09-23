import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentMessage } from "../../types/jiraCreate";

type Props = {
  messages: AgentMessage[];
  busy: boolean;
  ready: boolean;
  onSend: (message: string) => void;
};

const GREETING =
  "Describe the change you need. I'll map it to Jira fields from live metadata and ask for any missing required details by name.";

export function CreateJiraAgentPanel({ messages, busy, ready, onSend }: Props) {
  const [draft, setDraft] = useState("");
  const listRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const resizeComposer = useCallback(() => {
    const node = textareaRef.current;
    if (!node) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(node.scrollHeight, 120)}px`;
  }, []);

  useEffect(() => {
    resizeComposer();
  }, [draft, resizeComposer]);

  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    list.scrollTop = list.scrollHeight;
  }, [messages, busy]);

  const submit = () => {
    const text = draft.trim();
    if (!text || busy || !ready) return;
    onSend(text);
    setDraft("");
    requestAnimationFrame(resizeComposer);
  };

  return (
    <section className="create-jira-agent chat-panel" aria-label="Create Jira Agent">
      <div className="panel-title">Create Jira Agent</div>
      <div className="chat-panel-body">
        <div className="chat-message-list" ref={listRef}>
          <div className="chat-message assistant">
            <span className="chat-message-author">Create Jira Agent</span>
            <div className="chat-message-content">{GREETING}</div>
          </div>
          {messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className={`chat-message ${message.role}`}>
              <span className="chat-message-author">{message.role === "user" ? "You" : "Create Jira Agent"}</span>
              <div className="chat-message-content">{message.content}</div>
            </div>
          ))}
          {busy && (
            <div className="chat-message assistant status">
              <span className="chat-message-author">Create Jira Agent</span>
              <div className="chat-message-content chat-thinking">Analyzing requirement…</div>
            </div>
          )}
        </div>
        <div className="chat-composer">
          <label htmlFor="create-jira-requirement" className="sr-only">
            Message the Jira agent
          </label>
          <textarea
            ref={textareaRef}
            id="create-jira-requirement"
            className="chat-composer-input"
            placeholder={ready ? "Describe the requirement…" : "Select project and issue type first…"}
            value={draft}
            rows={1}
            disabled={busy || !ready}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                submit();
              }
            }}
          />
          <button
            type="button"
            className="chat-composer-send"
            aria-label="Send message"
            disabled={busy || !ready || !draft.trim()}
            onClick={submit}
          >
            ➤
          </button>
        </div>
      </div>
    </section>
  );
}
