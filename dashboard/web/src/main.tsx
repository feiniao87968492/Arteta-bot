import React from 'react';
import ReactDOM from 'react-dom/client';
import { App } from './App';
import { BackgroundVideo } from './components/BackgroundVideo';
import './styles.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BackgroundVideo />
    <App />
  </React.StrictMode>
);
