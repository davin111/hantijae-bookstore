import React from 'react';
import { renderInline, stripMarks } from './richText';

describe('renderInline', () => {
  it('wraps **text** in <strong> and keeps the rest as plain text', () => {
    const parts = renderInline('앞 **굵게** 뒤');
    expect(parts).toHaveLength(3);
    expect(parts[0]).toBe('앞 ');
    expect(React.isValidElement(parts[1]) && (parts[1] as React.ReactElement).type).toBe('strong');
    expect((parts[1] as React.ReactElement).props.children).toBe('굵게');
    expect(parts[2]).toBe(' 뒤');
  });

  it('leaves text without marks untouched and never parses HTML', () => {
    expect(renderInline('<b>그대로</b>')).toEqual(['<b>그대로</b>']);
  });

  it('ignores an unmatched ** pair', () => {
    expect(renderInline('별표 ** 하나')).toEqual(['별표 ** 하나']);
  });
});

describe('stripMarks', () => {
  it('removes bold marks for plain previews', () => {
    expect(stripMarks('**첫 줄** 둘째')).toBe('첫 줄 둘째');
  });
});
