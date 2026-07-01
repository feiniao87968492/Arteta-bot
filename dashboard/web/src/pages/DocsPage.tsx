import { useEffect, useMemo, useState } from 'react';
import { marked } from 'marked';
import { apiGet } from '../api/client';

type DocNode = {
  type: 'directory' | 'file';
  name: string;
  path: string;
  children?: DocNode[];
};

type DocFile = { path: string; content: string };
type SearchResult = { path: string; excerpt: string };

function sanitizeMarkdownHtml(html: string): string {
  const template = document.createElement('template');
  template.innerHTML = html;
  template.content.querySelectorAll('script, iframe, object, embed').forEach(node => node.remove());
  template.content.querySelectorAll('*').forEach(node => {
    for (const attribute of Array.from(node.attributes)) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim().toLowerCase();
      if (name.startsWith('on') || value.startsWith('javascript:')) {
        node.removeAttribute(attribute.name);
      }
    }
  });
  return template.innerHTML;
}

function TreeNode({ node, onOpen }: { node: DocNode; onOpen: (path: string) => void }) {
  if (node.type === 'file') {
    return <button onClick={() => onOpen(node.path)}>{node.name}</button>;
  }
  return (
    <div className="tree-group">
      <strong>{node.name}</strong>
      <div>{(node.children || []).map(child => <TreeNode key={child.path} node={child} onOpen={onOpen} />)}</div>
    </div>
  );
}

export function DocsPage() {
  const [tree, setTree] = useState<DocNode[]>([]);
  const [file, setFile] = useState<DocFile | null>(null);
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    apiGet<DocNode[]>('/api/docs/tree').then(setTree).catch(err => setError(String(err)));
  }, []);

  const renderedMarkdown = useMemo(() => {
    if (!file) return '';
    return sanitizeMarkdownHtml(marked.parse(file.content, { async: false }));
  }, [file]);

  async function open(path: string) {
    setError('');
    setFile(await apiGet<DocFile>(`/api/docs/file?path=${encodeURIComponent(path)}`));
  }

  async function search() {
    if (!query.trim()) {
      setResults([]);
      return;
    }
    setResults(await apiGet<SearchResult[]>(`/api/docs/search?q=${encodeURIComponent(query)}`));
  }

  return (
    <div className="docs-page-layout">
      <section className="panel page-panel docs-search-panel">
        <h2>全文搜索</h2>
        <div className="toolbar docs-search-toolbar">
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索文档和知识库" />
          <button onClick={search}>搜索</button>
        </div>
        {results.length > 0 && (
          <div className="docs-search-results">
            {results.map(result => (
              <button key={result.path + result.excerpt} onClick={() => open(result.path)}>
                <span>{result.path}</span>
                <small>{result.excerpt}</small>
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="docs-content-layout">
        <section className="panel page-panel docs-tree-panel">
          <h2>文档目录</h2>
          {error && <p className="error-text">{error}</p>}
          {tree.map(node => <TreeNode key={node.path} node={node} onOpen={open} />)}
        </section>
        <section className="panel page-panel docs-reader-panel">
          <h2>{file?.path || 'Markdown 预览'}</h2>
          {file ? (
            <article className="markdown-preview" dangerouslySetInnerHTML={{ __html: renderedMarkdown }} />
          ) : (
            <p className="muted">请选择一个 Markdown 文件</p>
          )}
        </section>
      </div>
    </div>
  );
}
