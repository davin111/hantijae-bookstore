import React from 'react';

const BOLD = /\*\*(.+?)\*\*/g;

/**
 * 소개글 한 줄에서 **굵게** 표기만 <strong>으로 바꾼다.
 * HTML 문자열을 끼워 넣지 않고 React 요소로 만들기 때문에 소개글에 태그가 섞여 있어도 그대로 글자로 보인다.
 */
export const renderInline = (line: string): React.ReactNode[] => {
  const parts: React.ReactNode[] = [];
  let last = 0;
  let key = 0;
  line.replace(BOLD, (match: string, inner: string, offset: number) => {
    if (offset > last) parts.push(line.slice(last, offset));
    parts.push(<strong key={key}>{inner}</strong>);
    key += 1;
    last = offset + match.length;
    return match;
  });
  if (last < line.length) parts.push(line.slice(last));
  return parts;
};

/** 목록 카드처럼 서식 없이 보여줄 곳에서 ** 표기를 지운다. */
export const stripMarks = (text: string): string => text.replace(BOLD, '$1');
