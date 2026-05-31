import { useNavigate } from "react-router-dom";
import { useDispatch } from "react-redux";
import { useEffect } from "react";
import { currentUsername } from '@putkoff/abstract-utilities';
import { logout } from "./../../Slices";
import { logoutUser } from '@putkoff/abstract-logins';

function Logout(props: any) {
    const navigate = useNavigate();
    const dispatch = useDispatch();

    useEffect(() => {
        const doLogout = async () => {
            await logoutUser();
            dispatch(logout({ user: currentUsername() }));
            navigate('/');
        };
        doLogout();
    }, [dispatch, navigate]);

    return <></>;
}

export default Logout;