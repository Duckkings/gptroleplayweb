import { useEffect, useState } from 'react';

type AuthMode = 'login' | 'register' | 'reset';

export function AuthPanel(props: {
  onLogin: (payload: { username: string; password: string }) => Promise<void>;
  onRegister: (payload: { username: string; password: string }) => Promise<void>;
  onResetPassword: (payload: { username: string; current_password: string; new_password: string }) => Promise<void>;
  error?: string | null;
  notice?: string | null;
}) {
  const [mode, setMode] = useState<AuthMode>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [localError, setLocalError] = useState('');

  useEffect(() => {
    setLocalError('');
  }, [mode, props.error]);

  useEffect(() => {
    if (mode !== 'reset') return;
    if (!props.notice) return;
    setMode('login');
    setPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setLocalError('');
  }, [mode, props.notice]);

  const modeTitle = mode === 'login' ? '登录' : mode === 'register' ? '注册' : '重置密码';
  const submitLabel = mode === 'login' ? '登录' : mode === 'register' ? '注册' : '重置密码';
  const errorText = localError || props.error || '';

  return (
    <div
      style={{
        maxWidth: 420,
        margin: '10vh auto',
        padding: 20,
        borderRadius: 14,
        border: '1px solid rgba(255,255,255,0.12)',
        background: 'rgba(0,0,0,0.25)',
        color: 'rgba(255,255,255,0.92)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0 }}>{modeTitle}</h2>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          {mode !== 'login' && (
            <button
              onClick={() => setMode('login')}
              style={{
                background: 'transparent',
                border: '1px solid rgba(255,255,255,0.16)',
                color: 'rgba(255,255,255,0.8)',
                padding: '6px 10px',
                borderRadius: 10,
                cursor: 'pointer',
              }}
            >
              切换到登录
            </button>
          )}
          {mode !== 'register' && (
            <button
              onClick={() => setMode('register')}
              style={{
                background: 'transparent',
                border: '1px solid rgba(255,255,255,0.16)',
                color: 'rgba(255,255,255,0.8)',
                padding: '6px 10px',
                borderRadius: 10,
                cursor: 'pointer',
              }}
            >
              切换到注册
            </button>
          )}
          {mode !== 'reset' && (
            <button
              onClick={() => setMode('reset')}
              style={{
                background: 'transparent',
                border: '1px solid rgba(255,255,255,0.16)',
                color: 'rgba(255,255,255,0.8)',
                padding: '6px 10px',
                borderRadius: 10,
                cursor: 'pointer',
              }}
            >
              重置密码
            </button>
          )}
        </div>
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
            style={{
              padding: '10px 12px',
              borderRadius: 10,
              border: '1px solid rgba(255,255,255,0.16)',
              background: 'rgba(0,0,0,0.25)',
              color: 'white',
            }}
          />
        </label>

        <label style={{ display: 'grid', gap: 6 }}>
          <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.75)' }}>{mode === 'reset' ? '当前密码' : '密码'}</span>
          <input
            value={password}
            type="password"
            onChange={(e) => setPassword(e.target.value)}
            placeholder="至少6位"
            style={{
              padding: '10px 12px',
              borderRadius: 10,
              border: '1px solid rgba(255,255,255,0.16)',
              background: 'rgba(0,0,0,0.25)',
              color: 'white',
            }}
          />
        </label>

        {mode === 'reset' && (
          <>
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.75)' }}>新密码</span>
              <input
                value={newPassword}
                type="password"
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="至少6位"
                style={{
                  padding: '10px 12px',
                  borderRadius: 10,
                  border: '1px solid rgba(255,255,255,0.16)',
                  background: 'rgba(0,0,0,0.25)',
                  color: 'white',
                }}
              />
            </label>
            <label style={{ display: 'grid', gap: 6 }}>
              <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.75)' }}>确认新密码</span>
              <input
                value={confirmPassword}
                type="password"
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="再次输入新密码"
                style={{
                  padding: '10px 12px',
                  borderRadius: 10,
                  border: '1px solid rgba(255,255,255,0.16)',
                  background: 'rgba(0,0,0,0.25)',
                  color: 'white',
                }}
              />
            </label>
          </>
        )}

        {props.notice ? <div style={{ color: '#9ee6a4', fontSize: 13, lineHeight: 1.5 }}>{props.notice}</div> : null}
        {errorText ? <div style={{ color: '#ffcc66', fontSize: 13, lineHeight: 1.5 }}>{errorText}</div> : null}

        <button
          onClick={async () => {
            setLocalError('');
            if (mode === 'login') {
              await props.onLogin({ username, password });
              return;
            }
            if (mode === 'register') {
              await props.onRegister({ username, password });
              return;
            }
            if (newPassword !== confirmPassword) {
              setLocalError('两次输入的新密码不一致');
              return;
            }
            await props.onResetPassword({ username, current_password: password, new_password: newPassword });
          }}
          style={{
            marginTop: 6,
            padding: '10px 12px',
            borderRadius: 12,
            border: '1px solid rgba(255,255,255,0.16)',
            background: 'linear-gradient(135deg, rgba(124,92,255,0.22), rgba(23,209,255,0.12))',
            color: 'rgba(255,255,255,0.92)',
            cursor: 'pointer',
          }}
        >
          {submitLabel}
        </button>
      </div>

      <div style={{ marginTop: 14, fontSize: 12, color: 'rgba(255,255,255,0.62)' }}>
        提示：远程部署时建议使用 HTTPS 并把 cookie 的 secure 打开。
      </div>
    </div>
  );
}
