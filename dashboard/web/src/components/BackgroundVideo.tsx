import { useEffect, useRef } from 'react';

export function BackgroundVideo() {
  const videoRef = useRef<HTMLVideoElement | null>(null);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = 0.8;
    }
  }, []);

  return (
    <video ref={videoRef} className="background-video" autoPlay muted loop playsInline aria-hidden="true">
      <source src="/bg.mp4" type="video/mp4" />
    </video>
  );
}
