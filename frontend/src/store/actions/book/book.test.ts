import axios from 'axios';
import { getBook } from './book';

jest.mock('axios');
// eslint-disable-next-line @typescript-eslint/unbound-method
const mockedGet = axios.get as jest.Mock;

describe('getBook', () => {
  beforeEach(() => {
    mockedGet.mockReset();
    mockedGet.mockResolvedValue({ data: { id: 1 } });
  });

  it('passes the preview token as a query param', async () => {
    await getBook(1, 'tok')(jest.fn());
    expect(mockedGet).toHaveBeenCalledWith('/api/book/1/', { params: { preview: 'tok' } });
  });

  it('sends no params without a preview token', async () => {
    await getBook(1)(jest.fn());
    expect(mockedGet).toHaveBeenCalledWith('/api/book/1/', { params: {} });
  });

  it('retries once when the first request fails (session race on first load)', async () => {
    mockedGet.mockReset();
    mockedGet.mockRejectedValueOnce(new Error('400')).mockResolvedValueOnce({ data: { id: 1 } });
    const dispatch = jest.fn();
    await getBook(1, 'tok')(dispatch);
    expect(mockedGet).toHaveBeenCalledTimes(2);
    expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ target: { id: 1 } }));
  });
});
