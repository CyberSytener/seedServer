/* ------------------------------------------------------------------ */
/* useNavigateView — sync Zustand view + react-router navigation       */
/* ------------------------------------------------------------------ */
import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useSagaStore } from '../store/useSagaStore';

type ViewKey = 'canvas' | 'gallery' | 'runs' | 'modules' | 'providers';

export function useNavigateView() {
  const navigate = useNavigate();
  const setView = useSagaStore((s) => s.setView);

  return useCallback(
    (view: ViewKey) => {
      setView(view);
      navigate(`/${view}`);
    },
    [setView, navigate],
  );
}
