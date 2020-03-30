import axios from 'axios';
import { Dispatch } from 'redux';
import { userConstants } from '../actionTypes';

const loginSuccess = (user: any) => ({
  type: userConstants.LOGIN_SUCCESS,
  target: user,
});

const loginFailure = (error: any) => {
  let actionType = null;
  switch (error.response.status) {
    case 403:
      actionType = userConstants.LOGIN_FAILURE;
      break;
    default:
      actionType = userConstants.LOGIN_FAILURE;
      break;
  }
  return {
    type: actionType,
    target: error,
  };
};

export const login = (
  username: string, password: string,
) => (dispatch: Dispatch) => axios.put('/api/user/login/', { username, password })
  .then((res) => dispatch(loginSuccess(res.data)))
  .catch((err) => dispatch(loginFailure(err)));


const signupSuccess = (user: any) => ({
  type: userConstants.SIGNUP_SUCCESS,
  target: user,
});

const signupFailure = (error: any) => ({
  type: userConstants.SIGNUP_FAILURE,
  target: error,
});

export const signup = (
  username: string, email: string, password: string,
) => (dispatch: Dispatch) => axios.post('/api/user/signup/')
  .then((res) => dispatch(signupSuccess(res.data)))
  .catch((err) => dispatch(signupFailure(err)));
