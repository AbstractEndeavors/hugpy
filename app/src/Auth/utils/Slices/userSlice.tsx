import {createSlice} from '@reduxjs/toolkit'

export const userSlice = createSlice({
    name: 'user',
    initialState: {
        account: null,
        isLoggedIn: false,
    },
    reducers: {
        login: (state, action) => {
            state.account = action.payload.account;
            state.isLoggedIn = true;
        },
        logout: (state, action) => {
            state.account = null;
            state.isLoggedIn = false;
        },
    }
})

export const {login, logout} = userSlice.actions
const userReducer = userSlice.reducer;
export default  userReducer
