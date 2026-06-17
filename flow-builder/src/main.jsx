import React from 'react';
import ReactDOM from 'react-dom/client';
import '@xyflow/react/dist/style.css';
import App from './App';
import './index.css';

function syncFlowTheme() {
  try {
    var t = localStorage.getItem('za-theme');
    if (t === 'dark' || t === 'light') {
      document.documentElement.setAttribute('data-theme', t);
    }
  } catch (e) {}
}
syncFlowTheme();
window.addEventListener('storage', function (e) {
  if (e.key === 'za-theme' && (e.newValue === 'dark' || e.newValue === 'light')) {
    document.documentElement.setAttribute('data-theme', e.newValue);
  }
});
window.addEventListener('zapaction-theme-change', function (e) {
  if (e.detail && e.detail.theme) {
    document.documentElement.setAttribute('data-theme', e.detail.theme);
  }
});
window.addEventListener('message', function (e) {
  if (e.data && e.data.type === 'zapaction-theme' && (e.data.theme === 'dark' || e.data.theme === 'light')) {
    document.documentElement.setAttribute('data-theme', e.data.theme);
  }
});

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
