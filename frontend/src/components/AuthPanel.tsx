import { useState } from 'react';

export function AuthPanel(props: {
  onLogin: (payload: { username: string; password: string }) => Promise<void>;
  onRegister: (payload: { username: string; password: string }) => Promise<void>;
  error?: string | null;
}) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');

  return (
    <div style={{
      maxWidth: 420,
      margin: '10vh auto',
      padding: 20,
      borderRadius: 14,
      border: '1px solid rgba(255,255,255,0.12)',
      background: 'rgba(0,0,0,0.25)',
      color: 'rgba(255,255,255,0.92)'
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12 }}>
        <h2 style={{ margin: 0 }}>{mode === 'login' ? '登录' : '注册'}</h2>
        <button
          onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
          style={{
            background: 'transparent',
            border: '1px solid rgba(255,255,255,0.16)',
            color: 'rgba(255,255,255,0.8)',
            padding: '6px 10px',
            borderRadius: 10,
            cursor: 'pointer'
          }}
        >
          切换到{mode === 'login' ? '注册' : '登录'}
        </button>
      </div>

      <p style={{ marginTop: 10, color: 'rgba(255,255,255,0.72)', lineHeight: 1.6, fontSize: 13 }}>
        这是多人模式：你的配置（API Key/模型）和存档会按账号隔离存储在服务器本机目录。
      </p>

      <div style={{ display: 'grid', gap: 10, marginTop: 14 }}>
        <label style={{ display: 'grid', gap: 6 }}>
          <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.75)' }}>用户名</span>
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="3-32位，仅字母数字_-"
            style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.16)', background: 'rgba(0,0,0,0.25)', color: 'white' }}
          />
        </label>
        <label style={{ display: 'grid', gap: 6 }}>
          <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.75)' }}>密码</span>
          <input
            value={password}
            type="password"
            onChange={(e) => setPassword(e.target.value)}
            placeholder="至少6位"
            style={{ padding: '10px 12px', borderRadius: 10, border: '1px solid rgba(255,255,255,0.16)', background: 'rgba(0,0,0,0.25)', color: 'white' }}
          />
        </label>

        {props.error ? (
          <div style={{ color: '#ffcc66', fontSize: 13, lineHeight: 1.5 }}>{props.error}</div>
        ) : null}

        <button
          onClick={async () => {
            if (mode === 'login') {
              await props.onLogin({ username, password });
            } else {
              await props.onRegister({ username, password });
            }
          }}
          style={{
            marginTop: 6,
            padding: '10px 12px',
            borderRadius: 12,
            border: '1px solid rgba(255,255,255,0.16)',
            background: 'linear-gradient(135deg, rgba(124,92,255,0.22), rgba(23,209,255,0.12))',
            color: 'rgba(255,255,255,0.92)',
            cursor: 'pointer'
          }}
        >
          {mode === 'login' ? '登录' : '注册'}
        </button>
      </div>

      <div style={{ marginTop: 14, fontSize: 12, color: 'rgba(255,255,255,0.62)' }}>
        提示：远程部署时建议使用 HTTPS 并把 cookie 的 secure 打开。
      </div>
    </div>
  );
}
