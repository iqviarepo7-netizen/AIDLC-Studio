import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "../../api";
import type { JiraFieldOption } from "../../types/jiraCreate";

type SearchKind = "user" | "issue" | "parent";

type Props = {
  id: string;
  value: string;
  options: JiraFieldOption[];
  placeholder?: string;
  required?: boolean;
  describedBy?: string;
  projectId?: string;
  issueTypeId?: string;
  searchKind: SearchKind;
  onChange: (value: string) => void;
};

export function JiraSearchableSelect({
  id,
  value,
  options,
  placeholder = "Select…",
  required,
  describedBy,
  projectId,
  issueTypeId,
  searchKind,
  onChange,
}: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [remoteOptions, setRemoteOptions] = useState<JiraFieldOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState<string>();
  const requestSeqRef = useRef(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const [menuRect, setMenuRect] = useState({ top: 0, left: 0, width: 0, maxHeight: 220 });

  const syncMenuPosition = useCallback(() => {
    const anchor = containerRef.current;
    if (!anchor) return;
    const rect = anchor.getBoundingClientRect();
    const gap = 4;
    const preferredMax = 220;
    const margin = 8;
    const spaceBelow = window.innerHeight - rect.bottom - margin;
    const spaceAbove = rect.top - margin;
    const openBelow = spaceBelow >= 120 || spaceBelow >= spaceAbove;
    const maxHeight = Math.min(preferredMax, openBelow ? spaceBelow - gap : spaceAbove - gap);
    const top = openBelow ? rect.bottom + gap : Math.max(margin, rect.top - maxHeight - gap);
    setMenuRect({
      top,
      left: rect.left,
      width: rect.width,
      maxHeight: Math.max(80, maxHeight),
    });
  }, []);

  useEffect(() => {
    if (!projectId || (searchKind === "parent" && !issueTypeId)) {
      setRemoteOptions([]);
      return undefined;
    }
    if (searchKind === "parent" && options.length > 0) {
      setRemoteOptions([]);
      return undefined;
    }
    const handle = window.setTimeout(() => {
      const requestId = ++requestSeqRef.current;
      setLoading(true);
      setSearchError(undefined);
      const request =
        searchKind === "user"
          ? api.jiraCreateUserSearch(projectId, query).then((response) => response.users)
          : searchKind === "parent"
            ? api.jiraCreateParentSearch(projectId, issueTypeId!, query).then((response) => response.issues)
            : api.jiraCreateIssueSearch(projectId, query).then((response) => response.issues);
      request
        .then((items) => {
          if (requestId !== requestSeqRef.current) return;
          setRemoteOptions(items.map((item) => ({ label: item.label, value: item.value })));
        })
        .catch(() => {
          if (requestId !== requestSeqRef.current) return;
          setRemoteOptions([]);
          setSearchError("Could not load search results.");
        })
        .finally(() => {
          if (requestId === requestSeqRef.current) setLoading(false);
        });
    }, 300);
    return () => window.clearTimeout(handle);
  }, [projectId, issueTypeId, query, searchKind, open, options.length]);

  const mergedOptions = useMemo(() => {
    const map = new Map<string, JiraFieldOption>();
    options.forEach((option) => map.set(option.value, option));
    remoteOptions.forEach((option) => map.set(option.value, option));
    if (value && !map.has(value)) {
      map.set(value, { label: value, value });
    }
    const needle = query.trim().toLowerCase();
    const all = [...map.values()];
    if (!needle) return all;
    return all.filter((option) => option.label.toLowerCase().includes(needle) || option.value.toLowerCase().includes(needle));
  }, [options, remoteOptions, value, query]);

  const selectedLabel = useMemo(() => {
    const map = new Map<string, JiraFieldOption>();
    options.forEach((option) => map.set(option.value, option));
    remoteOptions.forEach((option) => map.set(option.value, option));
    if (value) return map.get(value)?.label ?? value;
    return "";
  }, [options, remoteOptions, value]);

  const displayValue = open ? query : selectedLabel || "";

  useLayoutEffect(() => {
    if (!open) return undefined;
    syncMenuPosition();
    const scrollParent = containerRef.current?.closest(".jira-create-scroll");
    const onReposition = () => syncMenuPosition();
    scrollParent?.addEventListener("scroll", onReposition, { passive: true });
    window.addEventListener("resize", onReposition);
    window.addEventListener("scroll", onReposition, true);
    return () => {
      scrollParent?.removeEventListener("scroll", onReposition);
      window.removeEventListener("resize", onReposition);
      window.removeEventListener("scroll", onReposition, true);
    };
  }, [open, syncMenuPosition, mergedOptions.length, loading]);

  useEffect(() => {
    const onDocClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (containerRef.current?.contains(target)) return;
      const list = document.getElementById(`${id}-listbox`);
      if (list?.contains(target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [id]);

  const showPlaceholder = !open && !displayValue;

  return (
    <div className="jira-select-field">
      <div
        className={`jira-control jira-combobox${open ? " jira-combobox-open" : ""}`}
        ref={containerRef}
      >
        <input
          ref={inputRef}
          id={id}
          type="text"
          role="combobox"
          aria-expanded={open}
          aria-describedby={describedBy}
          aria-autocomplete="list"
          aria-controls={`${id}-listbox`}
          required={required && !value}
          className={`jira-combobox-input${showPlaceholder ? " jira-combobox-input--placeholder" : ""}`}
          placeholder={loading ? "Searching…" : placeholder}
          value={displayValue}
          disabled={!projectId}
          onFocus={() => {
            setOpen(true);
            setQuery("");
          }}
          onChange={(event) => {
            setOpen(true);
            setQuery(event.target.value);
            if (!event.target.value.trim()) onChange("");
          }}
          onKeyDown={(event) => {
            if (event.key === "Escape") {
              setOpen(false);
              setQuery("");
            }
          }}
        />
      </div>
      {open &&
        typeof document !== "undefined" &&
        createPortal(
          <ul
            id={`${id}-listbox`}
            className="jira-create-surface jira-combobox-list jira-combobox-list--floating"
            role="listbox"
            style={{
              top: menuRect.top,
              left: menuRect.left,
              width: menuRect.width,
              maxHeight: menuRect.maxHeight,
            }}
          >
            {mergedOptions.length === 0 && !loading && <li className="muted jira-combobox-empty">No matches</li>}
            {mergedOptions.map((option) => (
              <li key={option.value || option.label}>
                <button
                  type="button"
                  role="option"
                  className={value === option.value ? "is-selected" : undefined}
                  aria-selected={value === option.value}
                  disabled={option.disabled}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => {
                    onChange(option.value);
                    setQuery("");
                    setOpen(false);
                  }}
                >
                  {option.label}
                </button>
              </li>
            ))}
          </ul>,
          document.body,
        )}
      {searchError && !open && <p className="muted jira-combobox-hint">{searchError}</p>}
    </div>
  );
}
