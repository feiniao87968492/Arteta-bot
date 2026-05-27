import { useRef, useState } from 'react';
import { apiPost } from '../api/client';

type ChatResponse = {
  reply: string;
  reply_format: 'image' | 'text';
  reply_image?: string;
  group_id: string;
  user_id: string;
  nickname: string;
  favor_delta: number;
  favor_level: string;
  favor: number;
  verify_hints: string[];
};

type AttachedImage = {
  id: string;
  name: string;
  dataUrl: string;
};

type ChatLine = {
  role: 'user' | 'assistant';
  text: string;
  image?: string;
  uploadedImages?: string[];
  meta?: string;
};

const MAX_IMAGES = 4;
const MAX_IMAGE_BYTES = 6 * 1024 * 1024;

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(reader.error || new Error('read failed'));
    reader.readAsDataURL(file);
  });
}

export function BotChatPage({ onOpenVerify }: { onOpenVerify: () => void }) {
  const [groupId, setGroupId] = useState('dashboard');
  const [userId, setUserId] = useState('dashboard-user');
  const [nickname, setNickname] = useState('Dashboard 球员');
  const [message, setMessage] = useState('');
  const [images, setImages] = useState<AttachedImage[]>([]);
  const [lines, setLines] = useState<ChatLine[]>([]);
  const [lastResult, setLastResult] = useState<ChatResponse | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState('');
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function onPickFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files || []);
    event.target.value = '';
    if (!selected.length) return;
    setError('');
    const room = MAX_IMAGES - images.length;
    if (room <= 0) {
      setError(`最多上传 ${MAX_IMAGES} 张图片`);
      return;
    }
    const accepted: AttachedImage[] = [];
    for (const file of selected.slice(0, room)) {
      if (!file.type.startsWith('image/')) {
        setError(`仅支持图片：${file.name}`);
        continue;
      }
      if (file.size > MAX_IMAGE_BYTES) {
        setError(`${file.name} 超过 ${Math.round(MAX_IMAGE_BYTES / 1024 / 1024)}MB 上限`);
        continue;
      }
      try {
        const dataUrl = await readFileAsDataUrl(file);
        accepted.push({
          id: `${Date.now()}-${file.name}-${Math.random().toString(36).slice(2, 8)}`,
          name: file.name,
          dataUrl,
        });
      } catch (err) {
        setError(`读取失败：${file.name}`);
      }
    }
    if (accepted.length) {
      setImages(current => [...current, ...accepted]);
    }
  }

  function removeImage(id: string) {
    setImages(current => current.filter(item => item.id !== id));
  }

  async function send() {
    const text = message.trim();
    if (!text && images.length === 0) return;
    const attached = images;
    setSending(true);
    setError('');
    setMessage('');
    setImages([]);
    setLines(current => [
      ...current,
      { role: 'user', text, uploadedImages: attached.map(item => item.dataUrl) },
    ]);
    try {
      const result = await apiPost<ChatResponse>('/api/bot-chat/messages', {
        message: text,
        group_id: groupId,
        user_id: userId,
        nickname,
        images: attached.map(item => item.dataUrl),
      });
      setLastResult(result);
      setLines(current => [
        ...current,
        {
          role: 'assistant',
          text: result.reply,
          image: result.reply_image,
          meta: `${result.favor_level} / 信任度 ${result.favor} / 本次 ${result.favor_delta >= 0 ? '+' : ''}${result.favor_delta}`,
        },
      ]);
    } catch (err) {
      setError(String(err));
    } finally {
      setSending(false);
    }
  }

  function onInputKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
      void send();
    }
  }

  const canSend = !sending && (Boolean(message.trim()) || images.length > 0);

  return (
    <div className="bot-chat-layout">
      <section className="panel page-panel bot-chat-control">
        <h2>机器人对话</h2>
        <p className="muted">在 Dashboard 后端直接调用阿尔特塔文本对话核心，可附带图片让视觉模型先识别。</p>
        <div className="bot-chat-fields">
          <label>群号<input value={groupId} onChange={event => setGroupId(event.target.value)} /></label>
          <label>用户 ID<input value={userId} onChange={event => setUserId(event.target.value)} /></label>
          <label>昵称<input value={nickname} onChange={event => setNickname(event.target.value)} /></label>
        </div>
        <textarea
          value={message}
          onChange={event => setMessage(event.target.value)}
          onKeyDown={onInputKeyDown}
          rows={5}
          placeholder="输入要发给塔子的消息，Ctrl/⌘ + Enter 发送（可纯图片）"
        />
        {images.length > 0 && (
          <div className="bot-chat-image-preview">
            {images.map(item => (
              <div key={item.id} className="bot-chat-image-thumb">
                <img src={item.dataUrl} alt={item.name} />
                <button type="button" onClick={() => removeImage(item.id)} aria-label={`移除 ${item.name}`}>×</button>
              </div>
            ))}
          </div>
        )}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          style={{ display: 'none' }}
          onChange={onPickFiles}
        />
        <div className="toolbar">
          <button type="button" disabled={sending || images.length >= MAX_IMAGES} onClick={() => fileInputRef.current?.click()}>
            {images.length >= MAX_IMAGES ? `已达 ${MAX_IMAGES} 张上限` : `添加图片（${images.length}/${MAX_IMAGES}）`}
          </button>
          <button disabled={!canSend} onClick={send}>{sending ? '思考中' : '发送消息'}</button>
          <button onClick={onOpenVerify}>打开功能验证</button>
        </div>
        {lastResult && <p className="muted">建议验证：{lastResult.verify_hints.join('、')}</p>}
        {error && <p className="error-text">{error}</p>}
      </section>

      <section className="panel page-panel bot-chat-transcript">
        <h2>对话记录</h2>
        {lines.length === 0 ? <p className="muted">暂无对话</p> : lines.map((line, index) => (
          <article key={index} className={`chat-bubble ${line.role}`}>
            <strong>{line.role === 'user' ? nickname : '阿尔特塔'}</strong>
            {line.uploadedImages && line.uploadedImages.length > 0 && (
              <div className="bot-chat-image-preview chat-uploaded">
                {line.uploadedImages.map((url, idx) => (
                  <div key={idx} className="bot-chat-image-thumb readonly">
                    <img src={url} alt={`上传图片 ${idx + 1}`} />
                  </div>
                ))}
              </div>
            )}
            {line.image
              ? <img className="chat-rendered-image" src={line.image} alt={line.text || '阿尔特塔回复'} />
              : (line.text ? <p>{line.text}</p> : null)}
            {line.meta && <small>{line.meta}</small>}
          </article>
        ))}
      </section>
    </div>
  );
}
