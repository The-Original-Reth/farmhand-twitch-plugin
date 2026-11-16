import { useEffect, useState } from "react";

// A phone, or any page this narrow (inside Farmhand the page is a frame, so this is the frame's own width): the Stream
// page goes to one column, the preview first and the panels under it. Kept current as the size changes.
export const PHONE = "(max-width: 760px)";

export function usePhone() {
  const read = () => (typeof window !== "undefined" && window.matchMedia ? window.matchMedia(PHONE).matches : false);
  const [phone, setPhone] = useState(read);
  useEffect(() => {
    if (!window.matchMedia) return undefined;
    const mq = window.matchMedia(PHONE);
    const onChange = () => setPhone(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return phone;
}
