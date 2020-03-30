import { userConstants } from '../../actions/actionTypes';
import { userStatus } from '../../../constants/constants';

const initialState = {
  me: {},
  getMeStatus: userStatus.NONE,
  loginStatus: userStatus.NONE,
  signupStatus: userStatus.NONE,
};

const reducer = (state = initialState, action: any) => {
  switch (action.type) {
    case userConstants.LOGIN_SUCCESS:
      return { ...state, loginStatus: userStatus.SUCCESS, me: action.target };
    case userConstants.LOGIN_FAILURE:
      return { ...state, loginStatus: userStatus.FAILURE };
    case userConstants.SIGNUP_SUCCESS:
      return { ...state, signupStatus: userStatus.SUCCESS };
    case userConstants.SIGNUP_FAILURE:
      return { ...state, signupStatus: userStatus.FAILURE };
    case userConstants.GET_ME_SUCCESS:
      return { ...state, getMeStatus: userStatus.SUCCESS };
    case userConstants.GET_ME_FAILURE:
      return { ...state, getMeStatus: userStatus.FAILURE };
    default:
      return { ...state };
  }
};

export default reducer;
