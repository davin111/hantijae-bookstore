import { userConstants } from '../../actions/actionTypes';
import { userStatus } from '../../../constants/constants';

const initialState = {
  loginStatus: userStatus.NONE,
  login: {},
};

const reducer = (state = initialState, action: any) => {
  switch (action.type) {
    case userConstants.LOGIN_SUCCESS:
      return { ...state, loginStatus: userStatus.SUCCESS, login: action.target };
    case userConstants.LOGIN_FAILURE:
      return { ...state, loginStatus: userStatus.FAILURE };
    default:
      return { ...state };
  }
};

export default reducer;
