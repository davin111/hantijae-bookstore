import { stateActions } from '../../actions/actionTypes';

const initialState = {
  modal: {
    loginModal: false,
    fullBasketModal: false,
    basketInfoModal: false,
  },
};

const reducer = (state = initialState, action: any) => {
  switch (action.type) {
    case stateActions.OPEN_LOGIN_MODAL:
      return { ...state, modal: { loginModal: true } };
    case stateActions.CLOSE_LOGIN_MODAL:
      return { ...state, modal: { loginModal: false } };
    case stateActions.OPEN_FULL_BASKET_MODAL:
      return { ...state, modal: { fullBasketModal: true } };
    case stateActions.CLOSE_FULL_BASKET_MODAL:
      return { ...state, modal: { fullBasketModal: false } };
    case stateActions.OPEN_BASKET_INFO_MODAL:
      return { ...state, modal: { basketInfoModal: true } };
    case stateActions.CLOSE_BASKET_INFO_MODAL:
      return { ...state, modal: { basketInfoModal: false } };
    default:
      return { ...state };
  }
};

export default reducer;
